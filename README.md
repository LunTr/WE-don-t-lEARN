# WE don't lEARN

一个用于分析并提取 WE Learn 课程页面答案的 Python 脚本仓库。

当前仓库包含两个主要脚本：

- [main.py](main.py)：主脚本。自动走课程页 -> AJAX `scoAddr` -> iframe 内容页的链路，并提取当前已支持题型的答案。
- [report.py](report.py)：诊断脚本。用于排查某个 `sco` 页面为什么提取不到答案，查看真实 iframe 页面和调试链路。

## 当前支持的题型

`main.py` 当前支持以下两类题型：

- `filling`：填空题，答案通常位于 `input[data-solution]`
- `choice`：选择题，答案通常位于 `div[data-controltype="choice"]` 内的 `li[data-solution]`

如果遇到新的题型，可以先用 [report.py](report.py) 诊断页面结构，再补充到 [main.py](main.py) 的提取逻辑中。

## 运行前提

请只在你**已登录且有权限访问**的课程页面上使用本仓库。

由于目标站点需要登录态，运行前必须准备好有效的 Cookie。

## 环境要求

建议环境：
## 注意安装依赖！
- Windows + Python 3
- 已安装以下依赖：
  - `requests`
  - `beautifulsoup4`
  - `lxml`

## 安装依赖

在仓库目录下执行：

```bash
py -3 -m pip install requests beautifulsoup4 lxml
```

如果你的环境里没有 `py` 启动器，也可以使用：

```bash
python -m pip install requests beautifulsoup4 lxml
```

## 准备 Cookie

### 1. 在浏览器中登录 WE Learn
先在浏览器中正常登录目标站点。

### 2. 打开开发者工具，找到目标课程请求
在浏览器开发者工具中，找到类似下面的页面请求：

```text
https://welearn.sflep.com/student/StudyCourse.aspx?cid=...&classid=...&sco=...
```

### 3. 复制请求头中的 `Cookie`
把完整的 Cookie 请求头值复制出来，格式通常类似：

```text
name1=value1; name2=value2; name3=value3
```

### 4. 在仓库根目录新建 `CookieValue.txt`
在仓库根目录创建一个文件：

- `CookieValue.txt`

把刚才复制出的**整行 Cookie 值**粘贴进去。文件内容应当只有一行，例如：

```text
ASP.NET_SessionId=xxxx; .AspNet.Cookies=yyyy; area=dbD
```
## 这里不会的话可以请教AI
注意：

- 文件名必须是 `CookieValue.txt`
- 文件内容是**纯 Cookie 字符串**，不要带 `Cookie:` 前缀
- 不要把个人 Cookie 上传到公开仓库

当前代码读取 Cookie 的位置：

- [main.py:44-53](main.py#L44-L53)
- [main.py:198](main.py#L198)
- [report.py:61-70](report.py#L61-L70)
- [report.py:286](report.py#L286)

## 修改目标课程页面

主脚本默认读取 [main.py](main.py) 顶部的 `STUDY_URL`：

- [main.py:10](main.py#L10)

例如：

```python
STUDY_URL = "https://welearn.sflep.com/student/StudyCourse.aspx?cid=584&classid=730891&sco=m-2-4-2"
```

如果你想切换到其他题目页面，只需要修改这一行里的 URL。

其中最常改的是查询参数中的：

- `cid`
- `classid`
- `sco`

## 运行主脚本

在仓库目录下执行：

```bash
py -3 main.py
```

或：

```bash
python main.py
```

程序会自动执行以下流程：

1. 读取 `CookieValue.txt`
2. 请求 `StudyCourse.aspx`
3. 从主页面提取：
   - `userid`
   - `courseid`
   - `scoid`
   - AJAX 地址
4. 请求 `Ajax/SCO.aspx?action=scoAddr...`
5. 解析真实 iframe 内容页地址
6. 请求 iframe 页面
7. 提取当前已支持题型的答案

### 主脚本输出示例

```text
main page:  https://welearn.sflep.com/student/StudyCourse.aspx?cid=...
ajax url:   https://welearn.sflep.com/Ajax/SCO.aspx?uid=...
iframe url: https://centercourseware.sflep.com/...
found 4 answer item(s)

[choice]
01. data-id=u3_19_1 index=1 solution=disabled
02. data-id=u3_19_2 index=2 solution=disabled / impaired
```

输出说明：

- 会先显示主页面、AJAX 地址和 iframe 地址
- 然后按题型分组输出
- 目前会输出 `[filling]` 或 `[choice]`

## 使用诊断脚本

如果某个页面运行 [main.py](main.py) 后：

- 提取结果为空
- 页面结构和已支持题型不一致
- 你怀疑真实内容不在主 HTML 中

可以使用 [report.py](report.py) 进行诊断。

### 修改诊断目标 URL
在 [report.py:285](report.py#L285) 修改目标 URL，例如：

```python
url = "https://welearn.sflep.com/student/StudyCourse.aspx?cid=584&classid=730891&sco=m-2-3-19"
```

### 运行诊断脚本

```bash
py -3 report.py
```

或：

```bash
python report.py
```

### 诊断脚本会输出什么

`report.py` 会输出：

- 主页面抓取结果
- `userid / courseid / scoid / ajaxUrl`
- `scoAddr` 返回值
- iframe 真实页面地址
- 是否在 iframe 内容页中发现 `data-solution`

同时还会生成这些调试文件：

- `debug_response.html`：主页面 HTML
- `debug_sco_addr.json`：`scoAddr` 接口返回内容
- `debug_iframe.html`：iframe 真实内容页 HTML

这些文件适合在无法提取答案时手动分析结构。

## 常见问题

### 1. 运行后提示找不到答案
先检查：

- `CookieValue.txt` 是否存在
- Cookie 是否过期
- `STUDY_URL` 是否是你当前能访问的课程页面
- 当前题型是否属于已支持的 `filling` / `choice`

如果以上都正常但仍提取失败，请先运行 [report.py](report.py)。

### 2. 只有主页面，没有真实题目内容
这是正常现象。

WE Learn 的课程内容通常不是直接写在主页面里，而是通过：

- `StudyCourse.aspx`
- `Ajax/SCO.aspx`
- iframe 内容页

这一整条链路动态加载。

所以不能只请求主页面，还需要继续请求 `scoAddr` 返回的真实 iframe 页面。

### 3. `cookie.txt` 还用吗？
当前代码**不直接使用** `cookie.txt`。

当前实际使用的是：

- `CookieValue.txt`

其中：

- `cookie.txt`：更像原始抓包记录，供人工参考
- `CookieValue.txt`：程序实际读取的纯 Cookie 字符串文件

## 文件说明

- [main.py](main.py)：主提取脚本
- [report.py](report.py)：诊断脚本
- `CookieValue.txt`：运行时需要的 Cookie 文件，不建议上传
- `debug_response.html`：诊断生成的主页面 HTML
- `debug_sco_addr.json`：诊断生成的 AJAX 返回值
- `debug_iframe.html`：诊断生成的 iframe 页面 HTML

## 上传仓库前建议

如果你准备把仓库上传到公开平台，建议先删除或不要提交以下内容：

- `CookieValue.txt`
- 任何包含个人 Cookie、账号、姓名、用户编号的信息文件
- 运行中生成的调试文件（如果其中包含敏感内容）

建议至少把这些文件加入 `.gitignore`：

```gitignore
CookieValue.txt
debug_response.html
debug_sco_addr.json
debug_iframe.html
```

## 后续扩展

如果后续遇到新的题型，可以继续扩展 [main.py:153-195](main.py#L153-L195) 中的提取逻辑。

目前推荐流程是：

1. 先在 [main.py](main.py) 中直接运行已有逻辑
2. 如果提取失败，使用 [report.py](report.py) 找出真实 iframe 页面结构
3. 根据新题型补充提取规则
