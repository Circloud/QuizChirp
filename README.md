<p align="center">
  <img src="quizchirp/assets/logo.png" width="160" alt="做个鸟测评">
</p>

<h1 align="center">「做个鸟测评」</h1>

<p align="center">
  <strong>又要测评？左键三下，让鸟回答。</strong>
</p>

<p align="center">
  简体中文 · <a href="README_EN.md">English</a>
</p>

<p align="center">
  「做个鸟测评」面向浏览器里的在线测评，例如秋招、春招笔试。<br>
  它把屏幕截图交给 Codex 作答，再用鸟鸣次数提示答案以规避检测。
</p>

https://github.com/user-attachments/assets/ba808b49-90bf-4ddb-b89f-c528b7a771ba

## 快速开始

1. 从 [Releases](https://github.com/Circloud/QuizChirp/releases) 下载对应平台的应用包并完整解压。

2. Windows 打开 `QuizChirp.exe`；macOS 将 `QuizChirp.app` 放入「应用程序」后打开，按提示授予屏幕录制和输入监听权限。

3. 按托盘或菜单栏提示完成 Codex 设置，等到状态显示「就绪」（Ready）。

<sub>当前构建未使用可信发布者签名，macOS 版未公证，首次打开可能遇到系统安全提示。</sub>

## 使用流程

1. **确认就绪**：打开应用，确认托盘菜单栏显示「就绪」（Ready）。

2. **提交题目**：打开测评页面。

   - **单屏题**：直接用**左键三连击**提交。
   - **跨屏题**：在前几屏逐屏**按住右键并左键三连击**，操作结束后即可松开右键，此时当前页面截图已被暂存。滚动到下一屏后重复执行以上操作，并在最后一屏只**左键三连击**，提交全部页面。

3. **听答案**：鸟鸣 1–6 声分别对应第 1–6 个选项（A–F）。无法确定唯一答案时会播放失败提示音。可在托盘选择「试听提示音」提前熟悉。

## 适用范围

面向浏览器内的在线测评。需要安装考试客户端、本地监考程序或到指定场所参加的测评超出适用范围。

## 免责声明

本项目仅供学习交流，请遵守测评规则，勿用于明确禁止外部辅助的场景。项目不保证答案准确性或规避检测的效果。Codex 客户端在本地运行，截图仍会提交至所使用的 AI 服务，请注意敏感信息。使用风险及后果由使用者自行承担，开发者不对使用或滥用造成的后果负责。

[音频来源与许可](quizchirp/sounds/LICENSE.txt)

## FAQ

<details>
<summary>QuizChirp 免费吗？需要付费订阅吗？</summary>

QuizChirp 源码公开，免费下载使用，也不另收模型调用费。它复用本机的 Codex，免费或付费的 ChatGPT 账号都可以登录。可用模型和额度取决于你的 ChatGPT 套餐。

</details>

<details>
<summary>只支持 Codex 吗？可以用其他本地模型或 Harness 吗？</summary>

目前只兼容 Codex 运行时，所有模型调用都通过 Codex。账号登录使用 QuizChirp 里独立保存的 ChatGPT 登录状态，首次启动时需要重新登录。

</details>

<details>
<summary>默认使用哪个模型？可以调整推理强度吗？</summary>

新配置默认使用 GPT-6.2 Sol（`gpt-6.2-sol`），推理强度为 `medium`。已有配置以文件里的值为准。要调整，从托盘或菜单栏选择「打开配置文件」，修改 `[ai]` 下的 `model` 和 `thinking_effort`，保存后重启 QuizChirp。可用的推理强度取决于所选模型。对应设置留空时，使用 Codex 的默认值。

</details>

<details>
<summary>显示「未找到兼容的 Codex」怎么办？</summary>

QuizChirp 默认在系统 `PATH` 和常见安装路径中查找 Codex。如果已经安装了兼容版本但应用没找到，选择「打开配置文件」，在 `[runtime]` 下的 `codex_bin` 填入 Codex 可执行文件的路径。保存后选择「重试」。本机没有兼容版本时，可直接选择「下载 Codex」。

</details>

<details>
<summary>本机已经登录过 Codex，为什么还提示「需要登录」？</summary>

QuizChirp 把自己的登录状态单独保存在独立的目录，和 Codex 隔离。首次启动时在托盘菜单选择「使用 ChatGPT 登录…」，并在浏览器里完成登录。下次启动会沿用这个登录状态。

</details>

<details>
<summary>QuizChirp 会收集使用数据吗？截图会发到哪里？</summary>

QuizChirp 本身不收集遥测数据，也不向项目维护者上传使用记录、日志或截图。提交题目时，应用把截图交给本机的 Codex，由 Codex 将模型请求发往你所用的模型服务。使用 ChatGPT 登录时，请求通过该账号使用 OpenAI 的服务。QuizChirp 的日志和保留的截图存放在本机。

</details>

<details>
<summary>支持哪些题型？</summary>

只支持有 2–6 个选项、且只有一个正确答案的单选题。选项按出现顺序对应 A–F，以题目实际的选项数量为准。

</details>

<details>
<summary>题目跨屏或画面里有多道题时，会回答哪一道？</summary>

Codex 先按顺序阅读所有截图，利用重叠内容衔接不同画面。同一道题的题干、选项和材料可以分布在不同截图中。鼠标位置只决定截取哪块屏幕。

然后按阅读顺序选第一道题干、全部选项和必要材料都齐全的单选题，跳过缺少内容、属于其他题型或选项数量超出范围的题目。没有符合条件的题，或无法为选中的题确定唯一正确选项时，就播放失败提示音。

</details>

<details>
<summary>可以换一种鼠标触发方式吗？</summary>

在托盘菜单的「触发方式」里可以切换为「中键单击」。跨屏暂存时按住右键再单击中键，最后一屏直接单击中键提交。

</details>
