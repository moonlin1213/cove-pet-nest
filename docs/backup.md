# 本地备份与恢复

```sh
cove-pet-nest backup ./private-backup
```

目标目录必须不存在。备份使用 SQLite 在线 backup API，包含一致的宠物数据库和数据库引用到的运行图片，并写 manifest.json 的 SHA-256。运行中的 WAL 不用手工复制。备份包含你自己的关系摘要与照顾记录，是私有数据，不要上传到源码仓库或作为公开样例。

凭据不进入备份。恢复到全新的数据目录会生成新的本机访问码和 host_token，需要重新配置宿主。

```python
from pathlib import Path
from cove_pet_nest.backup import restore_backup
restore_backup(Path('private-backup'), Path('new-private-data'))
```

恢复先验证文件白名单、哈希和数据库 quick_check，拒绝覆盖已经存在的目录。完成后将 PET_NEST_DATA_DIR 指向 new-private-data，再启动小屋。请保留原始目录与备份，直到验证你自己的宠物、粮仓、图片和照顾记录。
