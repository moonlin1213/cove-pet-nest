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
