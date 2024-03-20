import os
import base64, hashlib, hmac, urllib

from flask import abort, jsonify

import googlemaps
import requests

from linebot import (
    LineBotApi, WebhookParser
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, LocationMessage, TextSendMessage,StickerSendMessage, 
    TemplateSendMessage, ButtonsTemplate, MessageAction, LocationAction, 
    CarouselTemplate, CarouselColumn, QuickReply, QuickReplyButton, CarouselTemplate, URIAction
)

# 質問用クラス
class Question:
    def __init__(self, text, choices):
        self.text = text
        self.choices = choices

# 質問群
q1 = Question("具体的には？", 
                      {"頭が痛い":"脳神経内科",
                       "息苦しい":"呼吸器科",
                       "歯が痛い":"歯科",
                       "目がかゆい":"眼科"})
q2 = Question("具体的には？", 
                      {"おなかが痛い":"消化器科",
                       "腰が痛い":"整形外科",
                       "肩こりがひどい":"マッサージ",
                       "動悸がする":"循環器科"})
q3 = Question("具体的には？",
                      {"手が痛い": "整形外科",
                       "手荒れがひどい":"皮膚科",
                       "足が痛い": "整形外科",
                       "足がむくんでいる":"内科"})
q4 = Question("具体的には？",
                      {"熱っぽい":"内科",
                       "だるい":"内科",
                       "眠れない":"内科",
                       "いらいらする":"心療内科"})
q5 = Question("どこがつらい？",
                      {"首から上":q1,
                       "手とか足":q3,
                       "それ以外":q2,
                       "全部":q4})
q6 = Question("無理してない？",
                      {"してない":[8515,16581242],
                       "してる":q5})
qaSet = Question("元気？",
                      {"元気！":q6,
                       "いまいち":q5,
                       "つらい":q5})
# ステータス保存
status = {}

def main(request):
    channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
    channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    place_api_key = os.environ.get('PLACE_API_KEY')
    google_map_url = "https://www.google.com/maps/search/?api=1"


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

            # ユーザーIDを取得する
            userid = event.source.user_id
            if isinstance(event.message, LocationMessage):                
                if userid in status:
                    # 位置情報を取得した場合、GooglePlaceAPIで周辺検索
                    search_word = status[userid]
                    if search_word.endswith("科"):
                        search_word = '病院　' + search_word
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
                        reply_data.append(TextSendMessage(text='近くに見当たらないみたいだ'))
                    else:
                        reply_data.append(TextSendMessage(text='探したよ'))
                        reply_data.append(TemplateSendMessage(
                            alt_text='検索結果',
                            template=CarouselTemplate(
                                columns=columns
                            )))
                    # ステータスを削除する
                    del status[userid]
                else:
                    # ユーザーIDが存在しない場合はやり直し
                    reply_data.append(TextSendMessage(text='ごめん\n何話してたっけ？'))
                line_bot_api.reply_message(
                    event.reply_token,
                    reply_data
                )
            elif isinstance(event.message, TextMessage):
                if userid in status:
                    # ユーザーIDが存在する場合、回答メッセージが質問セットの回答選択肢にあるか確認
                    if event.message.text in status[userid].choices:
                        # 存在する場合は次の質問があるか確認
                        next_action = status[userid].choices[event.message.text]
                        if isinstance(next_action, Question):
                            # 次の質問がある場合は質問セットを更新
                            status[userid] = next_action
                            # セットし直した質問セットをもとにボタンテンプレートを作成
                            reply_data.append(make_button_template(next_action))
                        elif isinstance(next_action, list):
                            # リストの場合はスタンプメッセージを編集
                            reply_data.append(
                                StickerSendMessage(
                                    package_id=next_action[0], sticker_id=next_action[1]
                                ))
                            # ステータスを削除する
                            del status[userid]
                        else:
                            # どちらでもない場合（文字列の場合）、テキストの末尾を判定
                            if next_action.endswith('科'):
                                messageText = '病院行け'
                            else:
                                messageText = next_action + '行け'
                            # ボタンに位置情報を返すアクションを設定する
                            location = [QuickReplyButton(action=LocationAction(label="位置情報を送る"))]
                            reply_data.append(
                                TextSendMessage(text=messageText, quick_reply=QuickReply(items=location)))
                            # ステータスを更新する
                            status[userid] = next_action
                    else:
                        # メッセージが選択肢に存在しない場合、もう一度聞き直す
                        reply_data.append(TextSendMessage(text='はぐらかさない'))
                        reply_data.append(make_button_template(status[userid]))
                else:
                    # ユーザーIDが存在しない場合、質問セットを設定
                    status[userid] = qaSet
                    # 質問セットをもとにボタンテンプレートを作成
                    reply_data.append(make_button_template(qaSet))

                # メッセージを返す
                line_bot_api.reply_message(
                    event.reply_token,
                    reply_data
                )
            else:
                continue

    return jsonify({ 'message': 'ok'})

def make_button_template(questions):
    # ボタンをリスト化する
    button_list = []
    # question内の回答選択肢dictからキーを全件取得
    for key in questions.choices:
        button_list.append(
            MessageAction(
                label=key,
                text=key
            )
        )
    # questionのtextを質問メッセージとして設定
    message_template = TemplateSendMessage(
        alt_text=questions.text,
        template=ButtonsTemplate(
            text = questions.text,            
            actions=button_list
        )
    )
    return message_template
