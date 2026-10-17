# 把灵宠屋接进你的 AI 应用

先启动小屋并领养一位宝宝，再接上下面两个宿主事件。需要凭据的是你的后端，不是模型；不要把 host_token 写进系统提示、网页 JS、公开配置或日志。

## 1. 回复完成后换粮

宿主成功保存最终可见回复后，向 `POST /api/integration/usage` 发送 JSON，使用本地 `credentials.json` 中的 host_token 作 Bearer 认证：

```json
{
  "source_id": "demo-app",
  "conversation_id": "demo-chat",
  "user_turn_id": "demo-user-turn-1",
  "reply_id": "demo-reply-1",
  "completed_at": 1800000000,
  "source_kind": "chat",
  "revision": 0,
  "new_user_utf8_bytes": 300,
  "final_visible_reply_utf8_bytes": 600,
  "usage": {"input_tokens": 9000, "output_tokens": 200}
}
```

时间示例是虚构值，实际使用本轮完成时间；首次领养前的事件不补历史粮。字节长度在宿主对新增用户消息与最终可见回复用 UTF-8 计算，只提交长度，不提交原文。

这个例子贡献 100 + 200 = 300 个计量 token，历史上下文中的其余输入不会换粮。支持 input/output、prompt/completion、Gemini promptTokenCount/candidatesTokenCount；Anthropic 输入与缓存字段按各自语义归一化。只给 total_tokens 无法区分输出，token 贡献为零，合格对话仍可领取当日基础粮。

支持 chat/shared_chat/regenerate/edit。失败事件传 `has_error=true` 不产粮。后台消息、图片任务、工具循环及模型自己上报的用量不能提交成用户参与的聊天。宿主是受信记账来源，服务无法独立验证宿主是否报告真实对话。

相同事件重试保留 source/reply/revision 与内容；同一 revision 改内容返回 409。重新生成保留 user_turn_id、使用新的 reply_id；迟到用量修订增加 revision。逻辑轮次只增加更高的贡献，日期固定为该轮首次被服务接受的事件中 completed_at 对应的本地日期；后续修订不改变归属日。宿主应按完成顺序提交，若跨日事件乱序到达，本版不回溯重分配粮食。ID 不应包含聊天原文或私人姓名。

## 2. 提供共同相处信号

宿主向 `POST /api/integration/relationship` 上报：

```json
{"event_id":"demo-life-1","occurred_at":1800000000,"summary":"虚构示例：一起安静地读了一会儿书。","signals":{"reading":2,"affection":1}}
```

每个权重范围 0–3，最多五个已知维度；同日同维度进入孵化时最多计 3。event_id 去重，不重复加权。摘要最多 600 字，建议去除姓名和原始对话。只有文字摘要而没有结构化信号时，不宣称已测得情感状态；核心不会另开模型猜亲密度。

关系摘要留在用户本地数据目录，普通状态与 MCP 不返回它。孵化使用结构化信号与真实照顾经历，冻结宠物身份、色泽、标记与性格；发送给图片服务的是生成描述，不是关系原文。

## 3. 让 AI 参与照顾

配置 MCP 后，AI 先用 nest_status 查看，再用 pet_care 执行。示例参数：

```json
{"action":"feed","pet_ids":["PET_ID_FROM_STATUS"],"request_id":"demo-feed-1"}
```

成功为 fed/played/comforted。full 表示已经吃饱，no_food 表示没有粮，pending 表示模样尚未准备；都不能说成刚完成照顾。使用相同 request_id 重试得到原回执，不再扣粮。

若你的应用没有 MCP 支持，受信后端携带 host_token 调用以下 HTTP 接口即可：

| 接口 | 用途 |
| --- | --- |
| GET /api/integration/nest?offset=0&limit=100 | 查询宠物 ID、粮食和真实照顾回执 |
| POST /api/integration/adoptions | 领养，参数 kind/name/request_id |
| POST /api/integration/care | 照顾，使用上面的参数示例 |

宿主接口把照顾者固定为 assistant，拒绝 actor 参数；网页接口固定 user。浏览器登录不能访问宿主接口。只有你自己的后端读取 host_token 并发请求，模型只提出动作、接收结果。首版没有远程托管或自动后台唤醒调度。

## 4. 导入普通宠物图集

需要准备鹦鹉等普通宠物时，可由受信后端向 `POST /api/integration/assets/PET_ID?request_id=demo-import-1` 发送图片原始字节并携带 host_token。图集必须为透明 RGBA、3 列×2 行六个正方格，尺寸至少 768×512，顺序 idle/blink/sleep/eat/seek_food/affection，最大 16 MiB。本接口不接受文件路径或下载 URL，不用于覆盖神秘蛋的固定孵化身份。

导入成功会终结该宠物的初始生成任务，后续不再为它提交请求，已在进行的晚到结果也不会覆盖导入图。如果请求此前已发送，导入无法撤销 Provider 侧可能发生的费用。

可运行的上报示例在 examples/host_events.py。示例不会创建真实关系、调用图片服务或自动领养，先在测试实例中领养。

## 5. 读取相册和记录生活片刻（v0.2.0）

MCP 新增只读 `pet_album(pet_id, offset=0, limit=20)`：返回阶段相册和有分页的生活事件。它不会调用图片服务。原来的三个工具与照顾请求保持兼容。

| 宿主接口 | 用途 |
| --- | --- |
| GET /api/integration/pets/{pet_id}/stages | 阶段历史、当前外观、冻结特征和任务状态 |
| GET /api/integration/life-events?pet_id=PET_ID&offset=0&limit=20 | 生活事件与照片任务；pet_id 可省略，limit 1–100 |
| POST /api/integration/life-events | 记录真实发生的共同生活事件 |
| POST /api/integration/photos | 根据已有事件明确排队一张生活照 |

记录事件示例（将时间与宠物 ID 换为本次真实值）：

```json
{"event_id":"demo-reading-1","occurred_at":1800000000,"kind":"reading","pet_ids":["PET_ID_FROM_STATUS"]}
```

`kind` 只接受 `reading`、`watching`、`listening`、`exploration`、`companionship`；pet_ids 必须是 1–4 个不同的现有宝宝。事件不能早于可用的外观记录，也不能超过当前时间 60 秒。服务按事件时刻查找已启用的外观并冻结引用。相同 event_id 与内容重试返回原记录，改内容返回 409；姓名、聊天、书名、照片说明等额外字段均拒绝。

成功照顾由核心自动产生事件，不需要宿主重复上报。关系信号和生活事件是两个独立用途：前者决定成长主题，后者提供照片的事实来源；需要两者时分别发送。服务信任宿主报告的事件，不会自动读取或核实宿主的聊天内容。

用返回的 `id` 请求照片：

```json
{"event_id":"EVENT_ID_FROM_LIFE_EVENTS","request_id":"demo-photo-1"}
```

照片接口固定操作者为 assistant。同一片刻最多一个任务，即使换 request_id 也返回同一个任务；图片处理由 `serve` 推进。请在用户明确想留下该片刻时调用，生成可能计费。图片配置、额度、失败和未知结果规则见 [图片服务说明](images.md)。`asset_ref` 为本地图片文件名，返回的 `asset_url` 相对于小屋网页，`/api/assets/` 使用浏览器会话认证，不能在外站直接当公开图片链接。

对应的网页接口是 GET `/api/pets/{pet_id}/stages`、GET `/api/life-events`、POST `/api/photos`，使用已有浏览器登录，会把操作者固定为 user。图片任务查询和手动重试使用 `/api/jobs/{id}` 与 `/api/jobs/{id}/retry`。不向宿主模型暴露任何本机凭据。

普通宠物初始图集导入仅在开始成长前可用。v0.2.0 已冻结下一阶段或完成成长后，导入返回 `appearance_locked_after_growth`；现有外观、照片和历史均保留。
