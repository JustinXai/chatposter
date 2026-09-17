# GitHub 仓库设置速填表

把下面内容复制粘贴到 GitHub 仓库的设置页面即可。**这一步比仓库名更影响可搜性。**

---

## 1. About → Description（仓库简介）

> 字数上限 350，下面这条 158 字符，中英混排塞满长尾词。

```
把微信群聊变成一张可直接发群的长图 · 本地解密微信4.x库，结构化分析群聊记录，生成宽1080高随内容的日报图 | WeChat group chat daily digest poster, local decrypt, offline
```

**为什么这么写**：GitHub 搜索会对 description 做全文匹配。把「微信群聊 / 长图 / 解密 / 日报图」
和英文的 `wechat group chat daily digest poster` 都塞进去，中英文两拨人都能搜到。

---

## 2. About → Website（可选）

有落地页就填，没有留空。**不要填微信号/二维码**，会被判定为营销仓库。

---

## 3. About → Topics（⭐ 最重要，这才是真正的流量入口）

GitHub 的 topic 聚合页是独立流量入口 —— 搜 `chat-summary` 的人会从
`github.com/topics/chat-summary` 点进来，**不看 stars 排序**。这是新项目唯一能挤进去的门。

**请把下面 20 个全部加上**（GitHub 上限就是 20 个）：

```
wechat
wechat4
wechat-group
group-chat
chat-summary
group-summary
chat-digest
daily-report
wechat-decrypt
sqlcipher
wcdb
chatlog
chat-history
poster-generator
screenshot
playwright
llm
deepseek
windows
local-first
```

**优先级排序逻辑**（如果 GitHub 提示超限，从后往前删）：

| 优先级 | Topics | 理由 |
|---|---|---|
| 🔴 必留 | `wechat` `wechat-group` `group-chat` `chat-summary` | 主干关键词，搜索量最大 |
| 🔴 必留 | `wechat4` `wechat-decrypt` `sqlcipher` `wcdb` | 技术壁垒词，会搜这些的人转化率最高 |
| 🟠 建议留 | `chat-digest` `group-summary` `daily-report` `chat-history` | 长尾词，竞争小 |
| 🟠 建议留 | `poster-generator` `local-first` `windows` | 差异化定位词 |
| 🟡 可选 | `chatlog` `playwright` `screenshot` `llm` `deepseek` | 生态关联词 |

---

## 4. 仓库名

```
chatposter
```

- ✅ 好拼、好记、无歧义
- ✅ 未被占用
- ⚠️ 缺点是**不含 `wechat` 关键词** —— 靠 topics 和 description 补位

---

## 5. 其他设置建议

| 设置项 | 建议值 | 说明 |
|---|---|---|
| Releases | 建议发一个 `v0.1.0` | 有 Release 的项目在搜索结果里权重略高 |
| Social preview | 上传 `docs/demo-tech.png` | 分享到群里/社交平台时的缩略图，**转化率影响极大**（蓝白科技风最适合对外） |
| Issues | 开启 | 缺省即可 |
| Discussions | 可选开启 | 有人问问题会沉淀内容，对搜索有帮助 |
| Wiki | 关闭 | 无内容时开着显得空 |

---

## 6. 发布后的自检

推上去之后，做这三件事确认可搜性：

1. **站内搜**：GitHub 搜 `wechat group summary`，看第几页能翻到
2. **Topic 页**：打开 `github.com/topics/chat-summary`，应该能看到你的仓库
3. **Google 搜**：`site:github.com chatposter wechat` —— 收录通常要 1~3 天

> 记住：**新仓库前两周基本没有自然流量**。真正拉动搜索的是
> 「有人点进来 + star + 在 README 里被引用」。所以首发渠道比 SEO 更重要 ——
> 发到你自己那群、V2EX、少数派、小红书，比等 GitHub 搜索靠谱得多。
