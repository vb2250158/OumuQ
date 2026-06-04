# Windows UTF-8 注意事项

浏览器 `fetch` 会按 UTF-8 发送 JSON。提交中文、日文或其他非 ASCII 文本时，优先使用 Web GUI。

Windows PowerShell 5 在发送非 ASCII JSON body 时，可能会用当前 ANSI 代码页编码，即使请求头写了 `charset=utf-8`。从 PowerShell 测试时，建议显式发送 UTF-8 bytes：

```powershell
$payload = @{
  text = '晚上好，今天辛苦了。'
  worker_url = 'http://127.0.0.1:8765'
  play = $true
  language = 'Japanese'
  character_id = 'jp_companion'
} | ConvertTo-Json -Compress

$bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
Invoke-RestMethod `
  -Method Post `
  -Uri 'http://127.0.0.1:8780/api/speak' `
  -ContentType 'application/json; charset=utf-8' `
  -Body $bytes
```

Python 脚本建议使用：

```powershell
py -X utf8 script.py
```

JSON 文件保持 UTF-8 编码。程序读取时应兼容 UTF-8 BOM。

如果同一段中文从浏览器提交正常、从 PowerShell 提交乱码，先检查请求编码，再排查 TTS 模型。
