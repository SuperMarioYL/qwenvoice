Output assets/demo.gif
Set FontSize 16
Set Width 1200
Set Height 600
Set Theme "Dracula"
Set Padding 20

# 10-minute happy path: init → record mom.wav → say → play
Type "qwenvoice init"
Enter
Sleep 2s

Type "# record a 5-15s clip of a family member as mom.wav, note the transcript"
Enter
Sleep 1s

Type 'qwenvoice say --voice mom.wav --ref-text "今天天气真好" \'
Enter
Type '  --text "你好，欢迎使用 QwenVoice。" -o hello.mp3'
Enter
Sleep 3s

Type "open hello.mp3"
Enter
Sleep 2s

Type "# hears the family voice read the sentence"
Enter
