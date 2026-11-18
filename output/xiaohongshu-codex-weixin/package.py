from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import json,html,zipfile
r=Path(__file__).parent
cards=json.loads((r/'cards.json').read_text())
md='# 用微信给 Codex 发任务：Mac 小白搭建指南\n\n审核稿，尚未发布。整理日期：2026-11-17。\n\n'
md+='本教程采用“让 Codex 协助配置”的跟做方式，不要求读者手写 JSON。原对话验证了本地调用和多轮记忆，后续日志显示微信消息进入网关，但最后一次 active writer 冲突没有修复结论。本机未重新绑定微信或重跑端到端部署。\n\n'
md+='## 发布标题与正文\n\n'+(r/'发布文案.txt').read_text()+'\n\n## 完整可复制配置请求\n\n在终端进入 `codex` 后，将下文整段发送：\n\n```text\n'+(r/'配置提示词.txt').read_text()+'\n```\n\n'
for tag,title,sub,blocks in cards:
 md+='## '+tag+' · '+title+'\n\n'+sub+'\n\n'
 for kind,txt in blocks:
  md+=('```bash\n'+txt+'\n```' if kind=='code' else txt)+'\n\n'
md+='''## 核对来源与版本说明

- [腾讯微信插件仓库](https://github.com/Tencent/openclaw-weixin)：扫码绑定和微信收发方式。
- [OpenClaw CLI backends 文档](https://docs.openclaw.ai/gateway/cli-backends)：当前文档已说明无内置 codex-cli 后端；因此本文明确锁定原记录版本，不将旧配置包装成最新版通用教程。
- [Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)：exec、resume 与 JSON 输出。
- [Node.js 下载](https://nodejs.org/en/download)：选择 Node 22 安装包。
- npm 元数据核对：openclaw@2026.5.12 要求 Node >=22.16；微信插件 2.4.10 的 peer dependency 为 OpenClaw >=2026.5.12。
- 原对话中实际安装的固定版本与后端参数、配置校验、本地两轮测试，以及最终 active writer 错误日志。原对话中的命令仅作证据，未按其历史指令操作本机。

## 审核结论

封面：内置 imagegen 生成，以用户两张猫图为形象参考。左猫两只前爪，右猫一只可见、另一只由电脑遮挡，未见额外肢体。内页由代码排版，避免生成式文字错字。无用户昵称、账号、私有会话 ID、token、二维码或设备主机名。

发布前仍需用户审阅风格和技术路线。教程不是已重新完成全链路实测的保证。旧版锁定是为了对应原记录，长期部署需重新评估版本与迁移路径。
'''
(r/'完整审核稿.md').write_text(md)
imgs=sorted(r.glob('[0-9][0-9].png'))
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>小红书图文审核</title><style>body{margin:0;background:#ebe8df;color:#123e3b;font:18px/1.7 system-ui}main{max-width:1100px;margin:auto;padding:35px}h1{font-size:32px}pre{white-space:pre-wrap;background:white;padding:25px;border-radius:16px}section{display:grid;grid-template-columns:repeat(2,1fr);gap:24px}img{width:100%;border-radius:12px}p{margin:10px 0}a{color:#a64424}@media(max-width:700px){section{grid-template-columns:1fr}}</style><main><h1>用微信给 Codex 发任务</h1><p>待审核 · 11 张图 · 尚未发布</p><p>固定版本复现；采用 Codex 协助搭建方式。最后的会话冲突未记录修复，不声称无故障。</p><p><a href="完整审核稿.md">完整稿与来源</a> · <a href="配置提示词.txt">复制配置提示词</a> · <a href="发布文案.txt">发布文案</a></p><pre>'''+html.escape((r/'发布文案.txt').read_text())+'</pre><section>'
for p in imgs:page+='<article><p>'+p.stem+' / 11</p><a href="'+p.name+'"><img src="'+p.name+'"></a></article>'
page+='</section></main></html>'
(r/'review.html').write_text(page)
w=330;h=440;gap=20
sheet=Image.new('RGB',(4*w+5*gap,3*(h+45)+gap),'#e8e5dc');d=ImageDraw.Draw(sheet)
for i,p in enumerate(imgs):
 im=Image.open(p).convert('RGB');im.thumbnail((w,h));x=gap+(i%4)*(w+gap);y=gap+(i//4)*(h+45)
 sheet.paste(im,(x,y));d.text((x,y+h+5),p.stem,fill='#123e3b',font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',22))
sheet.save(r/'总览.jpg',quality=92)
with zipfile.ZipFile(r/'发布素材.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in imgs+[r/'发布文案.txt',r/'配置提示词.txt',r/'完整审核稿.md',r/'review.html']:z.write(p,p.name)
