# go-hospital-bot
質問に答えると「病院行け」というBOTです

最初のメッセージはなんでもいいです。
何を言っても「元気？」と聞いてきます。

提示される選択肢をタップして会話を進めると、一部例外を除いて「病院行け」と返してきます。

位置情報の送信を促してくるので、言われるままに位置情報を教えると症状に合わせた診療科でGoogleMapを検索した結果を表示します。

以下環境・APIを使って動作します。
* Google Cloud Functions（ランタイム：Python 3.9）
* Google Place API
* LINE Messaging API
* Google Generative AI（Gemini）API

# 注意
応答内容はGoogle Generative AI（Gemini）によるものであり、専門家のアドバイスに代わるものではありません。

詳細はGeminiAPI利用規約（https://ai.google.dev/terms）等をご参照ください。

応答内容には誤りを含む可能性がありますので、ご留意の上でご使用ください。
