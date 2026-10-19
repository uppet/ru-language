# 包目录静态协议与本地原型

本实现是可用本地 fixture 验证的只读目录客户端及本地发布工具。它不包含公共部署、账号、认证、远程上传接口、后台服务或网络写入口。将来增加远程发布时，认证与授权必须缺省拒绝，不能沿用本地文件写权限作为线上授权。

## 文件布局（format 1）

```text
registry/
  index.json
  packages/
    工程.json
  archives/
    <sha256>.tar.gz
```

文件使用 UTF-8。HTTPS 请求包详情时，对包名进行 URL percent encoding，例如 `packages/%E5%B7%A5%E7%A8%8B.json`。磁盘文件名仍然是 `工程.json`；常规静态 HTTP 服务会解码 URL。名称必须是合法单一如言标识符，不接受路径或查询字符串。

`index.json`：

```json
{
  "format": 1,
  "packages": [
    {"name": "工程", "description": "基础力学"}
  ]
}
```

`packages/工程.json`：

```json
{
  "format": 1,
  "name": "工程",
  "description": "基础力学",
  "versions": {
    "1.0.0": {
      "archive": "archives/<64位小写sha256>.tar.gz",
      "sha256": "<64位小写sha256>",
      "requires": ">=0.21.0 <1.0.0",
      "dependencies": {
        "工具": {
          "目录": "https://registry.example.test",
          "包": "工具包",
          "版": ">=1.0.0 <2.0.0"
        }
      }
    }
  }
}
```

示例摘要为占位文字，实际文件必须填入归档字节的真实 SHA-256。版本必须是无前导零的三段非负整数。版本范围与集录采用相同的 exact／比较区间语法。

归档地址可以是目录根下的安全相对 URL，或无凭据、查询参数、片段的 HTTPS URL。拒绝 HTTP、其他协议、`..`、绝对本地路径、反斜线、重复编码、编码后的路径分隔符及控制字符。本地客户端只读本地相对归档，不会因元数据中的 HTTPS 地址而联网。 HTTPS 来源还拒绝路径中的 `.`／`..` 段、重复斜线及 ASCII 字符的 percent 编码别名，避免同一实际请求形成多个来源身份；非 ASCII UTF-8 路径统一编码，中文包名仍然支持。

缺少文件、包名不符、格式错误、重复 JSON 字段、错误来源描述、版本或摘要不合法都会返回“包错误”，不存在来源 fallback。索引不能出现重复包名。

## 命令行

```sh
ru registry search 力学 --registry ./registry
ru registry info 工程 --registry ./registry
ru registry versions 工程 --registry ./registry
ru registry dependencies 工程 1.0.0 --registry ./registry
ru registry download 工程 1.0.0 --registry ./registry -o 工程-1.0.0.tar.gz
ru registry publish ./工程 --registry ./registry
```

只读子命令也接受 `--registry https://registry.example.test`；发布只接受本地目录。download 要求输出文件不存在，不覆盖旧文件。`ru deps sync [目录]` 是依赖的显式获取入口：有锁时只恢复精确版本，`--locked` 还要求锁存在，`--update` 才重选。恢复取旧版本时仍核锁中归档摘要，目录不可用或同版本内容变化不会触发升级；完整缓存命中无需目录在线。run／check／build 不会调用目录网络读写。

## 客户端 API

```python
from rulang.package_registry import RegistryClient, LocalRegistry, client_for

remote = RegistryClient("https://registry.example.test")
local = LocalRegistry("./registry")
reader = client_for("./registry")  # HTTPS 字符串选择 RegistryClient

reader.search("力学")                  # [{name, description}, ...]
reader.info("工程")                    # 完整包元数据，含 versions
reader.versions("工程")                # 按数字版本升序排列
reader.dependencies("工程", "1.0.0")   # alias -> 来源描述典
data, metadata = reader.download("工程", "1.0.0")
```

`download` 返回经过 SHA-256 检查的归档字节和版本元数据；返回记录另含 `name` 与 `version`。它本身不解压。依赖同步使用公共安全解压器，在临时目录验证后再写缓存。SHA-256 能检查内容与元数据是否一致，不能替代目录身份认证或发布者签名。

搜索对名称和介绍做不区分大小写的子串匹配；空查询列出所有条目。首版没有分页、排序权重、模糊搜索或搜索服务。

`RegistryClient(base_url, fetcher=callable)` 支持离线契约测试；callable 接受一个完整 URL 并返回 bytes。正常客户端使用受限 HTTPS 下载器及验证过的重定向。客户端限制元数据为 2 MiB、归档为 32 MiB；本地读取采用相同边界。

## 本地发布

```python
from rulang.package_registry import publish_local

record = publish_local("./工程", "./registry")
print(record["version"], record["sha256"])
```

发布按以下顺序进行：

1. 静态解析 `集录.ru`，核查包名、版本、依赖与如言版本约束。
2. 检查公开入口属于将发布的源码集合，拒绝符号链接及包外路径。
3. 只打包集录和源码根下的 `.ru` 普通文件，保留相对路径。默认源码根是 `src`。不打包 README、其他资源、`集锁.json`、VCS 目录、常见缓存或依赖缓存目录。
4. 生成确定性的 tar.gz：固定顺序、时间戳、属主与权限，相同字节输入得到相同摘要。归档不含绝对路径。
5. 在临时目录用同步相同的安全解压器复核，再重新静态解析归档内集录；限制压缩大小、单文件大小、展开总量和文件数。递归检查全部路径依赖：目标必须在归档内并含有效集录，公开源码必须存在，依赖图不得循环或超过数量限制。
6. 持有本地写锁，拒绝任何已存在的包名／版本，包括字节完全相同的重复发布。先写内容寻址归档，再更新包元数据，最后更新搜索索引。

每个文件均通过同目录临时文件、fsync 和原子替换提交。普通写入失败会按反向顺序恢复已修改文件；已存在的版本与归档不会被覆盖。静态多文件目录不是数据库事务：并发读者可能短暂看到旧索引与新详情；进程崩溃或磁盘故障不保证跨文件事务回滚。因此此原型没有声称提供可直接部署的高可用发布服务。内容寻址归档先于引用它的元数据写入，避免可见元数据指向尚未写好的归档。

`.publish-lock` 防止并发发布。进程被强制终止后可能遗留该目录，后续发布明确报错；应先检查目录完整性，再手动清理锁。程序不会自动删除未知锁或其他发布进程的数据。

发布不会执行源码、hook、安装脚本或自动同步依赖，也不代替完整 `ru check`／三端运行测试。清单没有介绍字段，因此新建本地索引的 description 默认为空；静态目录维护者可以单独提供介绍。路径依赖保持原描述，不会自动拷贝外部包或转为远程依赖；只能引用已经随源码根内的 `.ru` 文件打包的内嵌包。缺少集录、越过归档边界（例如顶层 `../lib`）或循环路径依赖会在写入目录前拒绝发布。递归检查不会访问 Git 或 HTTPS，也不会调用依赖同步；其他包应使用可获取的 Git／目录依赖。

## 验证范围

`tests/test_package_registry.py` 完全使用临时本地目录和注入的读取函数，不需要公网或线上账号。覆盖搜索／介绍／版本／依赖／下载契约、中文 URL、内容摘要不符、非法 URL、错误元数据、大小限制、符号链接逃逸、公开源文件缺失、不可变版本、确定性归档、写锁、内嵌路径依赖完整性与循环检测，以及发布失败回滚。此套件不代表已验证公共服务部署、真实 TLS 端点或任意第三方静态托管配置。
