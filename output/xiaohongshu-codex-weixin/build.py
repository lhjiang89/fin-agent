from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import json,re
R=Path(__file__).parent
F='/System/Library/Fonts/STHeiti Medium.ttc'
M='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
BG='#F7F3E8'; INK='#123E3B'; ACC='#DF744E'
prompt='''请按以下要求帮我在这台 Mac 搭建微信→Codex 桥接。先检查环境，逐步执行，每步解释结果，遇到错误先排查，不要假装成功。
1. 复用我已登录的 Codex CLI。独立目录 ~/.local/share/codex-weixin；若已存在就先检查并备份，不覆盖现有配置。不改其他 OpenClaw 实例。
2. 在该目录本地安装 openclaw@2026.5.12 和 @tencent-weixin/openclaw-weixin@2.4.10。使用独立 state、config 和 workspace。创建 ./wx 包装命令，固定 Node 绝对路径，并设置 OPENCLAW_STATE_DIR 和 OPENCLAW_CONFIG_PATH。
3. 网关 mode=local、bind=loopback、port=19846，使用随机 token 鉴权。端口冲突先告诉我。会话 dmScope=per-account-channel-peer。
4. plugins.allow 包含 openai 和 openclaw-weixin；从本地 node_modules 加载微信插件并启用。主模型用 codex-cli/加上我账号实际可用的模型名，先用 codex exec 验证，不要照抄别人的模型名。
5. codex-cli 后端使用本机 codex 绝对路径；首轮 codex exec --json --skip-git-repo-check --sandbox workspace-write；续聊 codex exec -c sandbox_mode=\"workspace-write\" resume --json --skip-git-repo-check {sessionId}。output 和 resumeOutput 均为 jsonl。不要绕过沙箱。
6. 验证 config validate，以及本地 agent 首轮回复和第二轮记忆。展示结果。然后给我扫码登录命令，等我在手机确认。二维码、token、身份信息不要写入公开材料。
7. 扫码后启动网关，再检查 channels status，等待我在微信里完成两轮实测。不要提前宣称全链路成功。先以前台运行，后台自启等验证成功后再配。'''
(R/'配置提示词.txt').write_text(prompt)
body='''标题：用微信给Codex发任务！Mac搭建教程

出门只带手机，也能从微信给 Mac 上的 Codex 发任务？可以用桥接实现🐱

这次让幺幺和德芙当讲解员，带你看懂原理、准备环境、扫码和验收。

📌先看懂原理
微信 ClawBot → 腾讯 iLink → Mac 上的 OpenClaw → Codex CLI；回复沿原路返回。OpenClaw 负责传话，Codex 负责执行。

📌这篇怎么跟
① 准备 Mac、微信和可用的 Codex 账号
② 安装 Node.js 22（≥22.16）和 Codex CLI，先登录
③ 按图把配置要求交给 Codex，让它逐项检查、搭建
④ 先验本地回复和上下文，再扫码
⑤ 微信里测两轮；通过后再设后台运行

适合小白的重点：不用自己手写配置文件，但每一步都要看“成功标志”，遇到报错先停在当前步骤。

⚠️版本要对齐
这是原搭建记录的固定版本复现：OpenClaw 2026.5.12＋微信插件 2.4.10。新版已调整 Codex 接入方式，不要直接混用命令；旧版方案也不等于长期维护建议。

⚠️我实际踩到的坑
• 桌面端的回复不会自动发到微信。
• 同一会话被桌面端和微信同时写入，会报 active writer；先退出占用该会话的客户端/终端，等待任务结束，再从微信重试。不要删会话文件。
• 电脑休眠、断网或服务退出，机器人就可能不回复。
• 扫码绑定的是机器人对话，不会自动获得读取全部聊天、代你给任意好友发消息的权限。

✅验收标准：微信收到指定回复＋下一轮记住暗号，才算最小链路跑通。

本文基于一次真实搭建记录整理；最后一轮会话冲突尚未记录修复结果。你自己的环境仍需按图验收。

#Codex #微信机器人 #AI工具 #Mac教程 #小白教程 #效率工具'''
(R/'发布文案.txt').write_text(body)
# Card blocks: label, title, subtitle, (kind, text)
cards=[
('01 / 原理','微信是遥控器，Mac 来干活','先理解 4 个角色，再开始配置。',[
('box','微信 ClawBot\n你从手机发送任务'),('box','腾讯 iLink ＋ 微信插件\n接收消息，把回复送回原对话'),('box','本地 OpenClaw 网关\n转交任务，关联每个微信会话'),('box','Codex CLI\n在 Mac 的工作目录里执行任务'),('note','回复沿原路返回。Mac 需要开机、联网、服务运行。\n这是桥接方案；不是 Codex 内置的微信扫码入口。')]),
('02 / 准备','先把“地基”准备好','适用：macOS；Windows 不照抄本篇。',[
('text','① 一台能联网的 Mac ＋ 手机微信\n② 一个有可用额度的 Codex 账号\n③ Node.js 22，版本至少 22.16'),('box','安装 Node.js\n浏览器打开 nodejs.org/en/download\n选择 v22 的 macOS Installer（.pkg）\n按提示安装，完成后重新打开终端'),('text','按 ⌘＋空格 → 搜索“终端”→ 回车\n每个代码框整段粘贴，再按一次回车。'),('code','node -v\nnpm -v'),('note','成功标志：两行都有版本号，node 为 v22.16 或更高的 22.x。\n出现 command not found：先重新打开终端检查安装。')]),
('03 / 登录','先确认 Codex 自己能用','桌面 App 能聊天，不代表终端 CLI 已安装或登录。',[
('text','在终端逐行执行，等待上一条完成：'),('code','npm install -g @openai/codex\ncodex --version\ncodex login\ncodex login status'),('box','登录时会出现网页或登录提示\n按终端指引，用自己的账号完成登录。\n不要把登录凭据、二维码发到公开评论区。'),('text','接下来输入下面这条，进入 Codex：'),('code','codex'),('note','成功标志：CLI 有版本、显示已登录，并能进入交互界面。\n若 npm 报权限错误，把完整报错交给 Codex 排查，别盲目 sudo。')]),
('04 / 让 AI 配置','把这段发给 Codex ①','下一张是同一条提示词的后半段，合并发送。',[
('prompt','请帮我在这台 Mac 搭建微信→Codex 桥接。先检查环境，逐步执行，每步解释结果；报错先排查。'),
('prompt','1. 复用已登录的 Codex CLI。在 ~/.local/share/codex-weixin 独立安装 openclaw@2026.5.12 和 @tencent-weixin/openclaw-weixin@2.4.10。目录已存在先备份，不覆盖其他实例。'),
('prompt','2. 使用独立 state、config 和 workspace。创建 ./wx，固定 Node 绝对路径，并设置 OPENCLAW_STATE_DIR、OPENCLAW_CONFIG_PATH。'),
('prompt','3. 网关 mode=local，bind=loopback，port=19846，随机 token 鉴权。端口冲突先告诉我。session.dmScope=per-account-channel-peer。'),
('prompt','4. plugins.allow 包含 openai、openclaw-weixin；从本地 node_modules 加载并启用微信插件。模型用 codex-cli/加我账号实际可用的模型名，先验证，不要照抄。'),
('note','图 5 和图 6 的文字是一条完整请求。可以用手机识别文字，\n复制到电脑后合并；发布正文也提供流程说明。')]),
('05 / 让 AI 配置','把这段发给 Codex ②','接上一张，一起发给 Codex。',[
('prompt','5. codex-cli 后端使用本机 codex 绝对路径。首轮与续聊参数如下，output 和 resumeOutput 都设为 jsonl。'),
('code','exec --json --skip-git-repo-check\n--sandbox workspace-write'),
('code','exec -c sandbox_mode=\\\"workspace-write\\\"\nresume --json --skip-git-repo-check\n{sessionId}'),
('prompt','6. 执行 config validate，并验证本地 agent 首轮回复和第二轮记忆，展示结果。然后给我扫码命令，等手机确认。二维码、token 和身份信息不要公开。'),
('prompt','7. 扫码后启动网关并检查 channels status，等我在微信完成两轮实测，再配后台自启。不要提前宣称全链路成功，不要绕过沙箱。'),
('note','上方是写入配置数组的参数示意，不是让你单独在终端执行。\n让 Codex 处理引号与数组；不要启用危险的绕过权限选项。')]),
('06 / 本地验收','先确认“电脑这一段”通了','下面在 Mac 终端运行，别发到微信。',[
('code','cd ~/.local/share/codex-weixin\n./wx config validate'),
('text','成功标志：显示 Config valid。接着测试：'),
('code','./wx agent --local --agent main \\\n  --message "记住暗号：奶茶，只回复已记住"\n./wx agent --local --agent main \\\n  --message "刚才的暗号是什么？"'),
('box','应当先收到“已记住”\n第二轮能回答“奶茶”\n这只证明本地调用和续聊，尚未证明微信连通。'),
('note','配置、模型不可用、登录过期或额度不足：先让 Codex 排查。\n本地测试未通过，不要跳到扫码后就宣布成功。')]),
('07 / 扫码绑定','让微信找到你的机器人','只扫描你刚在自己电脑上生成的绑定码。',[
('code','cd ~/.local/share/codex-weixin\n./wx channels login \\\n  --channel openclaw-weixin'),
('text','用手机微信扫一扫 → 查看授权信息 → 确认。\n二维码过期：重新执行上面的登录命令。'),
('text','绑定成功后，在这个终端启动网关：'),
('code','./wx gateway run'),
('text','保持窗口打开。新开一个终端标签页检查：'),
('code','cd ~/.local/share/codex-weixin\n./wx channels status'),
('note','成功标志：Gateway reachable；微信通道为 running。\n只显示“已绑定”还不够，下一页必须做真实消息测试。')]),
('08 / 微信验收','手机上测两轮，才算跑通','打开绑定后的「微信 ClawBot」对话。',[
('box','第一轮发送\n记住暗号“猫粮”，只回复“连接成功”。\n\n预期：收到“连接成功”。'),
('box','第二轮发送\n刚才的暗号是什么？\n\n预期：能回答“猫粮”。'),
('text','为什么换了一个暗号？\n确认记住的是微信里的这段上下文，\n而不是刚才的本地测试会话。'),
('note','两轮都对，才说明微信收发＋Codex 调用＋续聊一起工作。\n长任务可能需要等待；不要连续重复发送同一项操作。')]),
('09 / 日常使用','先用通，再配置后台','前台试跑通过后，把下面这段交给 Codex。',[
('prompt','请为这个独立桥接配置 macOS launchd 登录后自启。使用 Node 和 codex 绝对路径、正确 PATH，明确 state 和 config 路径，日志放在独立 state 目录。先检查同名服务，备份后再修改；不要影响其他网关。'),
('prompt','配置前提醒我在前台网关窗口按 Ctrl+C 停止，避免端口冲突。启动后台服务后验证 channels status，并给出查看日志、停止和恢复服务的准确命令。'),
('box','使用时记住\n• Mac 保持开机、联网，避免自动休眠。\n• 登录后自启不等于关机也能接收任务。\n• 文件默认放独立 workspace。\n• 模型调用仍受账号额度与权限限制。'),
('note','workspace-write 限制写入范围，不等于所有文件绝对不可读。\n先在空的测试目录使用，不要直接连接敏感生产资料。')]),
('10 / 避坑清单','这 4 个坑，提前知道','来自原对话的实际问题与能力边界。',[
('box','① 桌面端回复没有出现在微信\n桌面端发起任务绕过网关。\n同一会话 ID ≠ 消息自动双向同步。'),
('box','② 出现 already has an active writer\n先退出占用同一会话的桌面/终端会话，\n等正在执行的任务结束，再从微信重试。\n不删会话文件；仍报错就查日志。'),
('box','③ 微信没有任何回复\n先查 Mac 休眠/断网，再查 channels status，\n再查登录、模型额度和网关日志。'),
('box','④ 能否读取所有聊天或代发给好友？\n本方案仅处理绑定的机器人对话。\n不会自动获得好友、群聊或全部聊天记录。'),
('note','原记录最后的会话冲突未见修复结论；本文不声称已修好。\n固定旧版本复现，与新版文档混用前必须重新验证。')])]

def font(n,mono=False):return ImageFont.truetype(M if mono else F,n)
def wrap(txt,ft,width):
 out=[]
 for line in txt.split('\n'):
  s=''
  for c in re.findall(r'[A-Za-z0-9_@./=<>-]+|.',line):
   if ImageDraw.Draw(Image.new('RGB',(1,1))).textlength(s+c,font=ft)>width and s:
    out.append(s);s=c
   else:s+=c
  out.append(s)
 return out
for idx,(tag,title,sub,blocks) in enumerate(cards,2):
 im=Image.new('RGB',(1080,1440),BG);d=ImageDraw.Draw(im)
 d.rounded_rectangle((62,55,390,111),radius=24,fill=INK)
 d.text((84,69),tag,font=font(25),fill='white')
 d.text((62,153),title,font=font(52),fill=INK)
 d.text((62,230),sub,font=font(27),fill=INK)
 y=303
 for kind,txt in blocks:
  size=30 if kind in ('text','box') else 28
  if kind=='code':size=27
  if kind=='note':size=24
  ft=font(size,kind=='code'); lines=wrap(txt,ft,894)
  lh=int(size*1.55); h=len(lines)*lh+36
  if kind in ('box','code','prompt'):
   d.rounded_rectangle((62,y,1018,y+h),radius=20,fill=INK if kind=='code' else '#E7EADF')
  for j,l in enumerate(lines):d.text((85,y+17+j*lh),l,font=ft,fill='white' if kind=='code' else INK)
  y+=h+18
 if y>1350:raise ValueError((idx,y))
 d.line((62,1360,1018,1360),fill='#C5CCBE',width=2)
 d.text((62,1380),'幺幺 & 德芙的 AI 小课堂 · 固定版本复现',font=font(21),fill=INK)
 d.text((925,1380),f'{idx:02d}/11',font=font(21),fill=INK)
 im.save(R/f'{idx:02d}.png')
(R/'cards.json').write_text(json.dumps(cards,ensure_ascii=False,indent=2))
