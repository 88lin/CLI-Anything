# MacroCLI Demo — gedit 完整测试方案

> **注意事项（测试前必读）**
> - 所有命令在**桌面终端**里跑，不能是 SSH 无头会话（需要 `$DISPLAY`）
> - `gedit_save_as` 用的菜单路径是 `[File, Save As...]`，如果你的 gedit 版本菜单文字不同（比如无省略号），需要改 yaml 里的 `menu_path`
> - 录制完的宏用 `--macro-file /path/to/xxx.yaml` 直接指定，无需注册到 manifest
> - 如果 AT-SPI 不可用（`semantic_ui available: false`），`menu_click` 步骤会失败，改用 `hotkey` 替代

## 目标

在 Linux 桌面机上，用 **gedit**（文本编辑器）演示 MacroCLI 的三条核心路径：

1. **手写宏** — 用已有的 YAML 宏定义执行 GUI 操作
2. **录制宏** — 操作一次 gedit，自动生成宏 YAML
3. **Gemini 辅助生成**（可选，需 API Key）

---

## 第一步：环境准备

在你的 Linux 桌面机上执行：

```bash
# 1. 安装 gedit（如果没有）
sudo apt install gedit          # Ubuntu/Debian
# sudo dnf install gedit        # Fedora
# sudo pacman -S gedit          # Arch

# 2. 安装 MacroCLI 系统依赖
sudo apt install xdotool wmctrl python3-pyatspi

# 3. 克隆仓库 / 进入已有目录
cd ~/CLI-Anything-with-GUI-Macro-System-/macrocli/agent-harness

# 4. 创建专用 conda 环境（或用已有的）
conda create -n macrocli python=3.11 -y
conda activate macrocli

# 5. 安装 MacroCLI 及可视化依赖
pip install -e ".[visual]"
# 等价于：pip install -e . mss Pillow numpy pynput

# 6. 验证安装
cli-anything-macrocli macro list
```

期望输出：
```
Available macros (7):
  export_file          Export a file from the target application...
  gedit_find_and_replace  Open Find & Replace in gedit...
  gedit_new_window     Open a new gedit window...
  gedit_save_as        Save the current gedit document...
  gedit_type_and_save  Type a line of text into gedit and save...
  transform_json       Read a JSON file, set a nested key...
  undo_last            Trigger an undo operation...
```

---

## 第二步：检查后端可用性

```bash
cli-anything-macrocli --json backends
```

期望（在桌面机上）：
```json
{
  "native_api":    { "available": true,  "priority": 100 },
  "gui_macro":     { "available": false, "priority": 80  },
  "visual_anchor": { "available": true,  "priority": 75  },
  "file_transform":{ "available": true,  "priority": 70  },
  "semantic_ui":   { "available": true,  "priority": 50  },
  "recovery":      { "available": true,  "priority": 10  }
}
```

> `visual_anchor` 需要 `mss Pillow numpy pynput` 全部安装  
> `semantic_ui` 需要 `xdotool` 或 `python3-pyatspi`

---

## Demo A：手写宏执行（semantic_ui + visual_anchor）

### A1. 打开 gedit（native_api 宏）

```bash
# 干跑确认参数正确
cli-anything-macrocli --dry-run --json macro run gedit_new_window

# 正式执行：打开一个新 gedit 窗口
cli-anything-macrocli --json macro run gedit_new_window
```

gedit 窗口应在 3 秒内弹出。

### A2. 在 gedit 里输入文字并保存（semantic_ui + visual_anchor）

```bash
# 在已打开的 gedit 里输入文字并 Ctrl+S 保存
cli-anything-macrocli --json macro run gedit_type_and_save \
    --param "text=Hello from MacroCLI! 🎉"
```

观察：光标出现在 gedit，逐字输入，然后触发保存。

### A3. 另存为指定路径（menu_click + wait_for_window）

```bash
cli-anything-macrocli --json macro run gedit_save_as \
    --param output_path=/tmp/macrocli_demo.txt
```

观察：
1. `File > Save As...` 菜单被自动点击
2. 等待对话框出现
3. 路径被输入，回车确认
4. 后置条件验证 `/tmp/macrocli_demo.txt` 存在

验证结果：
```bash
cat /tmp/macrocli_demo.txt
```

### A4. 查找替换（hotkey + type_text）

```bash
cli-anything-macrocli --json macro run gedit_find_and_replace \
    --param find_text=Hello \
    --param replace_text=Hi
```

观察：`Ctrl+H` 弹出对话框，自动填写两个字段，执行 Replace All，关闭。

---

## Demo B：录制宏（自动生成）

这个演示"录制一次，以后可以重复调用"。

```bash
# 1. 开始录制，给宏命名 my_gedit_workflow
cli-anything-macrocli macro record my_gedit_workflow \
    --output-dir /tmp/macrocli_recording
```

终端显示：
```
Recording 'my_gedit_workflow'. Press Ctrl+Alt+S to stop.
```

**现在手动操作 gedit**（录制器会捕获这些动作）：
1. 点击 gedit 文本区
2. 输入几个字
3. 按 `Ctrl+S`
4. 点击菜单 `File`
5. 点击 `Save As`
6. 输入文件名
7. 按回车

**停止录制：**
```
Ctrl+Alt+S
```

录制结束，自动生成：
```
/tmp/macrocli_recording/
├── my_gedit_workflow.yaml        ← 宏定义文件
└── my_gedit_workflow_templates/
    ├── step_001_click.png        ← 每个点击的截图模板
    ├── step_002_click.png
    └── ...
```

查看生成的宏：
```bash
cat /tmp/macrocli_recording/my_gedit_workflow.yaml

# 或直接查 info（用 --macro-file）
cli-anything-macrocli --json macro run my_gedit_workflow \
    --macro-file /tmp/macrocli_recording/my_gedit_workflow.yaml --dry-run
```

重放录制的宏：
```bash
# 用 --macro-file 直接指定 yaml 文件，无需注册到 manifest
cli-anything-macrocli --json macro run my_gedit_workflow \
    --macro-file /tmp/macrocli_recording/my_gedit_workflow.yaml
```

---

## Demo C：Gemini 辅助生成（可选）

需要 Gemini API Key（免费额度够用）：
获取地址：https://aistudio.google.com/app/apikey

```bash
# 安装 Gemini 依赖
pip install google-generativeai

# 打开 gedit，然后截图分析
cli-anything-macrocli macro assist gedit_close_tab \
    --goal "Close the current tab in gedit without saving" \
    --screenshot current \
    --api-key $GEMINI_API_KEY \
    --output /tmp/gedit_close_tab.yaml
```

输出示例：
```
Sending screenshot to Gemini (gemini-1.5-flash)...
✓ Generated 3 steps → /tmp/gedit_close_tab.yaml

  Templates to capture (use 'macro capture-template'):
    templates/001_wait_image.png: Close button in the tab bar
```

查看生成结果：
```bash
cat /tmp/gedit_close_tab.yaml
```

---

## Demo D：模板截图（visual_anchor 基础）

这演示如何为 `click_image` 创建模板。

```bash
# 1. 打开 gedit，定位"New"按钮的屏幕坐标（用鼠标悬停或 xdotool）
# 假设 New 按钮在 (120, 55)，大小约 40x30

# 2. 截取模板
cli-anything-macrocli macro capture-template \
    templates/gedit_new_button.png \
    --x 100 --y 40 --width 60 --height 40

# 3. 写一个使用该模板的宏
cat > /tmp/gedit_click_new.yaml << 'EOF'
name: gedit_click_new
version: "1.0"
description: Click the New button in gedit toolbar.
steps:
  - id: click_new
    backend: visual_anchor
    action: click_image
    params:
      template: templates/gedit_new_button.png
      confidence: 0.85
      timeout_ms: 3000
EOF

# 4. 执行（在 gedit 窗口上测试）
cli-anything-macrocli macro run gedit_click_new \
    --macro-file /tmp/gedit_click_new.yaml --json
```

---

## 完整自动化测试脚本

把上面的步骤串成一个脚本，验证全链路：

```bash
#!/bin/bash
# demo_test.sh — MacroCLI gedit 完整链路测试

set -e
echo "=== MacroCLI Demo Test ==="

# 确保没有旧的 gedit 残留
pkill gedit 2>/dev/null || true
sleep 0.5

echo ""
echo "--- Step 1: Open gedit ---"
cli-anything-macrocli --json macro run gedit_new_window
sleep 1.5

echo ""
echo "--- Step 2: Type text ---"
cli-anything-macrocli --json macro run gedit_type_and_save \
    --param "text=MacroCLI demo: $(date)"
sleep 0.5

echo ""
echo "--- Step 3: Save As ---"
OUTPUT=/tmp/macrocli_demo_$(date +%s).txt
cli-anything-macrocli --json macro run gedit_save_as \
    --param output_path="$OUTPUT"
sleep 0.5

echo ""
echo "--- Step 4: Verify output ---"
echo "File content:"
cat "$OUTPUT"
echo ""
echo "File size: $(wc -c < $OUTPUT) bytes"

echo ""
echo "--- Step 5: Find & Replace ---"
cli-anything-macrocli --json macro run gedit_find_and_replace \
    --param find_text=MacroCLI \
    --param replace_text=MacroCLI✓
sleep 0.5

echo ""
echo "=== All steps passed ==="
```

运行：
```bash
chmod +x demo_test.sh
./demo_test.sh
```

---

## 常见问题

**Q: `semantic_ui` 报 "xdotool not found"**
```bash
sudo apt install xdotool
```

**Q: `menu_click` 报 "AT-SPI application not found"**
```bash
sudo apt install python3-pyatspi
# 然后重启 gedit（需要 AT-SPI 服务在启动时就运行）
```

**Q: `visual_anchor` 报 "no display"**
- 确认在桌面终端（不是 SSH）里运行
- 或设置 `export DISPLAY=:0`

**Q: 录制时 Ctrl+Alt+S 没反应**
- 确认焦点在终端而不是 gedit
- 或用 `--timeout 30`（30 秒后自动停止）

**Q: 模板匹配失败（confidence 太高）**
```yaml
# 把 confidence 调低
confidence: 0.70   # 默认 0.85
```

---

## 下一步：对接更复杂的应用

同样的流程适用于任何 GUI 应用：

| 应用 | 推荐后端 | 备注 |
|------|----------|------|
| Inkscape | `native_api` (`--actions`) + `semantic_ui` | 原生 CLI 支持很好 |
| GIMP | `native_api` (Script-Fu) | 有完整脚本接口 |
| LibreOffice | `native_api` (`--headless`) + `semantic_ui` | UNO API |
| draw.io | `file_transform` + `visual_anchor` | XML 格式，可直接改文件 |
| 无 CLI 的应用 | `macro record` + `visual_anchor` | 录制一次，模板匹配回放 |
