<p align="center">
  <img src="quizchirp/assets/logo.png" width="160" alt="QuizChirp">
</p>

<h1 align="center">QuizChirp</h1>

<p align="center">
  <strong>Another quiz? Three left clicks. Let the bird answer.</strong>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · English
</p>

<p align="center">
  QuizChirp is for browser-based assessments such as online tests during spring and autumn recruitment.<br>
  It sends screenshots to Codex for answers and uses the number of bird calls to convey them and evade detection.
</p>

## Quick start

1. Download the application package for your platform from [Releases](https://github.com/Circloud/QuizChirp/releases) and extract it in full.

2. On Windows, open `QuizChirp.exe`. On macOS, move `QuizChirp.app` to Applications and open it, allowing screen recording and input monitoring when prompted.

3. Follow the tray or menu bar prompts to set up Codex and wait for the status to show **Ready**.

<sub>Current builds do not use trusted publisher signing, and the macOS app is not notarized, so the first launch may encounter system security prompts.</sub>

## Usage

1. **Check that QuizChirp is ready**: Open the app and confirm that the tray or menu bar shows **Ready**.

2. **Submit the question**: Open the assessment page.

   - **Single-screen question**: **Triple-click the left mouse button** to submit it.
   - **Question that requires scrolling**: For each view before the final one, **hold the right mouse button and triple-click the left mouse button** to save the screenshot. Release the right button after the gesture, then scroll and repeat. On the final view, **triple-click the left mouse button** on its own to submit all views together.

3. **Listen for the answer**: One to six bird calls correspond to the first through sixth choices (A–F). A failure sound plays if QuizChirp can't determine a single correct choice. Use **Preview sounds** in the tray to get familiar with the sounds.

## Supported assessments

QuizChirp is intended for browser-based assessments. Assessments that require an installed exam client, local proctoring software, or attendance at a designated venue are outside its scope.

## Disclaimer

This project is for learning and discussion. Follow assessment rules and do not use it where external assistance is explicitly prohibited. Neither answer accuracy nor monitoring evasion is guaranteed. The Codex client runs locally and sends screenshots to the AI service in use. Take care with sensitive information. Users assume the risks and consequences of use, and the developer accepts no responsibility for consequences arising from use or misuse.

[Audio sources and licenses](quizchirp/sounds/LICENSE.txt)

## FAQ

<details>
<summary>Is QuizChirp free? Do I need a paid subscription?</summary>

QuizChirp's source code is public, and the app is free to download and use. It uses Codex on your computer and charges no extra fees for model calls. You can sign in with a free or paid ChatGPT account. Available models and usage limits depend on your ChatGPT plan.

</details>

<details>
<summary>Is Codex the only option? Can I use another local model or harness?</summary>

QuizChirp only supports the Codex runtime, and all model calls go through Codex. QuizChirp stores its own ChatGPT sign-in, so you'll need to sign in the first time you open the app.

</details>

<details>
<summary>Which model is used by default? Can I change the reasoning effort?</summary>

New configurations use GPT-6.2 Sol (`gpt-6.2-sol`) with `medium` reasoning effort. Existing configurations use their saved values. To change either setting, choose **Open configuration file** from the tray or menu bar, edit `model` and `thinking_effort` under `[ai]`, and restart QuizChirp after saving. The reasoning levels available depend on the model. Leave either setting blank to use the Codex default for it.

</details>

<details>
<summary>What should I do if I see “No compatible Codex found”?</summary>

QuizChirp looks for Codex on your system `PATH` and in common installation locations. If a compatible version is installed but wasn't found, select **Open configuration file** and set `codex_bin` under `[runtime]` to the path of the Codex executable. Save the file and select **Retry**. If your computer has no compatible version, select **Download Codex**.

</details>

<details>
<summary>Why do I see “Sign-in required” if I've already signed in to Codex?</summary>

QuizChirp stores its sign-in in its own directory on your computer, separate from your existing Codex sign-in. The first time you open QuizChirp, choose **Sign in with ChatGPT...** from the tray menu and finish signing in through your browser. QuizChirp reuses that sign-in the next time it starts.

</details>

<details>
<summary>Does QuizChirp collect usage data? Where do my screenshots go?</summary>

QuizChirp collects no telemetry and sends no usage data, logs, or screenshots to its maintainers. When you submit a question, QuizChirp hands the screenshots to your local Codex runtime, which sends the model request to the model service you use. With ChatGPT sign-in, requests use OpenAI's service under your account. QuizChirp's logs and any retained screenshots stay on your computer.

</details>

<details>
<summary>Which question types are supported?</summary>

QuizChirp supports multiple-choice questions with 2–6 choices and exactly one correct answer. Choices are mapped to A–F in order of appearance, using only as many letters as there are choices.

</details>

<details>
<summary>Which question is answered when a question spans multiple views or several questions are visible?</summary>

Codex reads all screenshots in order and uses overlapping content to join the views. A question's text, choices, and supporting material can appear in different screenshots. The pointer only determines which display to capture.

Codex selects the first single-answer question in reading order that has 2–6 choices and includes the full question, all choices, and any required supporting material. A failure sound plays if no question qualifies or if Codex can't determine a single correct answer for the selected question.

</details>

<details>
<summary>Can I change the mouse gesture?</summary>

Choose **Trigger** → **Middle single-click** in the tray or menu bar. To save a view, hold the right mouse button and click the middle button once. On the final view, click the middle button on its own to submit all views.

</details>
