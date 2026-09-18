把二维码放这里
==============

1. 把你的微信二维码图片存成 assets/qr.png（或 .jpg）
2. 在 config.py 或环境变量里填上你的名字：

   CHATPOSTER_CONTACT_NAME=你的名字
   CHATPOSTER_CONTACT_ROLE=你的身份或公司      （可选）
   CHATPOSTER_CONTACT_NOTE=扫码加我            （可选，默认就是这个）

存好之后，以后每张日报图的右下角都会自动带上「名字 + 二维码」。

想换个别的位置：设 CHATPOSTER_QR 指向任意图片路径即可。

不配也能跑 —— 右下角会显示一个虚线空位，提示你这里可以放二维码。
整块都不想要：把 CHATPOSTER_CONTACT_NAME 和二维码都留空，版面会自动收回去。

⚠️ 二维码是你的个人信息，本项目已在 .gitignore 里排除 assets/ 下的图片，
   不会被提交到仓库。也请不要把它写进公开的分析稿 JSON。
