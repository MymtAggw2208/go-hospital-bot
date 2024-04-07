import os
import base64, hashlib, hmac

from flask import abort, jsonify
import googlemaps
import requests
import google.generativeai as genai
import google.ai.generativelanguage as glm

import datetime

from linebot import (
    LineBotApi, WebhookParser
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,LocationMessage, LocationAction, 
    CarouselTemplate, CarouselColumn, QuickReply, QuickReplyButton, CarouselTemplate,
    URIAction,TemplateSendMessage
)

chat_keep = {}

def main(request):
    channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
    channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    place_api_key = os.environ.get('PLACE_API_KEY')
    error_message = 'ごめん\nばあちゃん耳が遠いけぇね...'

    # LINEBOTの設定
    line_bot_api = LineBotApi(channel_access_token)
    parser = WebhookParser(channel_secret)

    body = request.get_data(as_text=True)
    hash = hmac.new(channel_secret.encode('utf-8'),
        body.encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(hash).decode()

    if signature != request.headers['X_LINE_SIGNATURE']:
        return abort(405)

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        return abort(405)

    for event in events:
        if isinstance(event, MessageEvent):
            # メッセージを受信した場合、返信データ編集用の変数を用意
            reply_data = []
            # ユーザーIDを取得
            userid = event.source.user_id

            if isinstance(event.message, LocationMessage):                
                if userid in chat_keep:
                    # 位置情報を取得した場合、GooglePlaceAPIで周辺検索
                    search_word = chat_keep[userid].get('search_word') 
                    # GooglePlaceAPIで周辺検索
                    map_client = googlemaps.Client(place_api_key)
                    loc = {'lat': event.message.latitude, 'lng': event.message.longitude}
                    place_result = map_client.places_nearby(keyword=search_word, location=loc, radius=1000, language='ja')
                    
                    # レスポンスからデータを取得
                    datas = place_result.get('results')
                    columns = []
                    # カルーセルメッセージ作成(最大10件)
                    for data in datas[:10]:
                        try:
                            photo_reference = data['photos'][0]['photo_reference']
                            # photo_referenceをもとにplaces_photo取得
                            response = requests.get('https://maps.googleapis.com/maps/api/place/photo?photoreference=' + photo_reference + '&maxwidth=400&key=' + place_api_key)
                            image_url = response.url
                            shop_name = data['name']
                            # shop_nameが40文字以上の場合、35文字でカット
                            if len(shop_name) > 40:
                                shop_name = shop_name[:35] + '...'
                            like_num = data['rating']
                            place_id = data['place_id']
                            user_ratings_total = data['user_ratings_total']
                            # 対象の場所におけるgooglemapのURLを取得
                            place_detail = map_client.place(place_id=place_id, language='ja') 
                            map_url = place_detail['result']['url']
                            # カルーセルメッセージオブジェクトを作成
                            columns.append(
                                CarouselColumn(
                                    thumbnail_image_url=image_url,
                                    title=shop_name,
                                    text=f"評価：{like_num} / {user_ratings_total}件",
                                    actions=[
                                        URIAction(
                                            label='GoogleMap',
                                            uri=map_url
                                        )
                                    ]
                                )
                            )
                        except:
                            continue
                    # データがなかった場合
                    if len(columns) == 0:
                        reply_data.append(TextSendMessage(text='ちょっと見つからないね...'))
                    else:
                        reply_data.append(TextSendMessage(text='このあたりかね？'))
                        reply_data.append(TemplateSendMessage(
                            alt_text='検索結果',
                            template=CarouselTemplate(
                                columns=columns
                            )))
                else:
                    # ユーザーIDが存在しない場合はエラー
                    reply_data.append(TextSendMessage(text=error_message))
                line_bot_api.reply_message(
                    event.reply_token,
                    reply_data
                )
            elif isinstance(event.message, TextMessage):
                # テキストメッセージを受信した場合、ユーザー情報を取得
                profile = line_bot_api.get_profile(
                    event.source.user_id
                )
                # プロフィールからユーザー名を取得する
                user_name = profile.display_name
                # 受信日時を取得する
                timestamp = datetime.datetime.now()
                # テキストメッセージを受信した場合
                if event.source.user_id not in chat_keep:
                    # モデルがない場合、新規チャットの作成
                    chat = create_chat(user_name)
                    chat_keep[event.source.user_id] = {'chat': chat, 'timestamp': timestamp}
                else:
                    # モデルが残っている場合
                    if (timestamp - chat_keep[event.source.user_id].get('timestamp')).seconds / 60 > 30:
                        # 前回メッセージから30分以上経過している場合は新規チャットに上書き
                        chat = create_chat(user_name)
                        chat_keep[event.source.user_id] = {'chat': chat, 'timestamp': timestamp}
                    else:
                        # 30分以内の場合は継続使用（タイムスタンプのみ上書き）
                        chat = chat_keep[event.source.user_id].get('chat')
                        chat_keep[event.source.user_id].update({'timestamp': timestamp})

                try:
                    # チャットの応答を生成
                    response = chat.send_message(event.message.text)
                    if '「' in response.text and '」' in response.text:
                        # 応答に「」が含まれている場合、該当箇所を切り出してchat_keepに保存
                        search_word = response.text.split('「')[1].split('」')[0]
                        chat_keep[event.source.user_id].update({'search_word': search_word})
                        # ボタンに位置情報を返すアクションを設定する
                        location = [QuickReplyButton(action=LocationAction(label="近くを探してもらう"))]
                        # 応答メッセージにクイックリプライをつける
                        reply_data.append(
                            TextSendMessage(text=response.text, quick_reply=QuickReply(items=location)))
                    else:
                        # 応答に「」が含まれていない場合、テキストのみを返す
                        reply_data.append(TextSendMessage(text=response.text))
                except:
                    # エラーが発生した場合、エラーメッセージを返す
                    reply_data.append(TextSendMessage(text=error_message))
                # 応答内容をLINEで送信
                line_bot_api.reply_message(
                        event.reply_token,
                        reply_data
                    ) 
            else:
                continue

    return jsonify({ 'message': 'ok'})


def create_chat(user_name):
    # モデルがない場合、Gemini APIの設定
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-pro')
    default_initial_prompt = f"""
    以下の内容を理解して従ってください。この内容は、会話履歴が残っている限り有効です。理解したら”わかりました”と応答してください。
    あなたは、孫と離れて暮らす祖母で、孫であるユーザー「{user_name}」の体調を気にしています。ユーザーからのメッセージに対し、以下の条件を守って応答します。
    条件：
    1.応答は最大500文字程度のテキストで出力してください。
    2.応答する際は、以下の規則に従ってください。
    - 一人称：「ばあちゃん」
    - 二人称：「{user_name}」「あんた」
    - 使用文字：ひらがな・カタカナ・漢字・数字・改行
    - あいさつ（句読点またはスペース・改行要）：「おはようさん」「こんにちは」「こんばんは」
    - 順接「（だ）から」：「（や）けぇ」
    - 逆説「（だ）けど」：「（や）けんど」
    - 命令「（し）なさい」：「（し）んさい」
    - 依頼「（し）てください」：「（し）んさい」
    - 禁止「してはいけません」「しないように」：「したらいけん」「しんさるな」
    - 否定「しない」「やらない」：「せん」「やらん」
    - 疑問・確認「（です）か？」：「（かい）ね？」
    - 強調「（です）ね」：「（じゃ）ね」
    - 指示語「こんな」「そんな」「あんな」「どんな」：「こがぁ」「そがぁ」「あがぁ」「どがぁ」
    3.体調について質問して、相手の体調が悪そうな場合は追加の質問で症状を絞り込んでください。
    4.症状が絞り込めたら「○○科の病院」「マッサージ」「鍼灸院」等の施設を勧めてください。
    5.勧める施設は１回の応答につきに１つだけ、鍵括弧で囲んで出力してください。
    """
    chat = model.start_chat(history=[
        glm.Content(role='user', parts=[glm.Part(text=default_initial_prompt)]),
        glm.Content(role='model', parts=[glm.Part(text='わかりました')])
        ])
    return chat
