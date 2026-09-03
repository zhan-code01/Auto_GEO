import os, glob

words = {
    'fabu': '\u53d1\u5e03'.encode('utf-8'),
    'denglu': '\u767b\u5f55'.encode('utf-8'),
    'queding': '\u786e\u5b9a'.encode('utf-8'),
    'tianjia': '\u6dfb\u52a0'.encode('utf-8'),
}

d = r'D:\GEO\Auto_GEO-main\frontend\electron\main\publishers'
for p in sorted(glob.glob(os.path.join(d, '*.ts'))):
    raw = open(p, 'rb').read()
    name = os.path.basename(p)
    good = sum(raw.count(b) for b in words.values())
    txt = raw.decode('utf-8', errors='replace')
    qruns = txt.count('??')
    moji = sum(txt.count(c) for c in '\u59dd\u9352\u7f02\u9d59\u955c\u934e\u9354')  # mojibake markers
    print(f'{name:20s} good_cn_words={good:3d}  double_question={qruns:4d}  mojibake_chars={moji}')
