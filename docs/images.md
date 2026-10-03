# 初始模样与神秘灵宠孵化

猫、狗和蛋有打包的通用素材。其他普通宠物可以导入自己的透明六格图集；也可以配置一次生成请求。神秘蛋达到门槛后使用冻结的关系信号与身份描述孵化。

配置以下环境变量，再启动 `cove-pet-nest serve`：

```sh
export PET_NEST_IMAGE_ENDPOINT='https://images.example.test/v1/images/generations'
export PET_NEST_IMAGE_MODEL='YOUR_IMAGE_MODEL'
export PET_NEST_IMAGE_KEY='YOUR_PRIVATE_KEY'
```

example.test 只是占位域名。endpoint 必须是你的完整生成接口地址，不能带凭据或查询参数。首版仅支持 OpenAI-compatible JSON 生成接口，响应需包含 data[0].b64_json，且支持透明背景、1536×1024 输出。没有实现任意 Provider 自动识别或返回 URL 的下载链。

外发内容只有通用画风、物种、固定外观锚点和六格动作要求，不包含聊天、关系摘要、人物名称、原始证据或你的宠物数据库。生成出的图集会经过尺寸、alpha 和本地 WebP 派生检查，并剥离输入图片 metadata。

每个宠物的初始或孵化阶段只有一个任务，最多每天成功/进行中三项。reserved 等待配置或名额；submitted 已提交；success 激活模样；failed 表示明确拒绝或图片处理失败；unknown 表示提交后结果不确定；superseded 表示已采用手动导入图集，旧生成任务终结且不可重试。提交后崩溃会在 180 秒租约过期后转 unknown，不能因此自动再发请求。

失败可在宝宝面板手动继续，重复的重试 request_id 不重复排队。unknown 必须确认“上次可能已计费”才能发送新请求。图片处理失败也可能已产生 Provider 费用，重试前查看自己的服务账单。

真实生成的质量取决于你选择的图片服务。测试图集和模拟断线只证明任务/恢复规则，不能替代真实服务与生成图视觉验收。
