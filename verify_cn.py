import sys

def analyze(path):
    raw = open(path, 'rb').read()
    targets = {
        'f_a_b_u': '\u53d1\u5e03'.encode('utf-8'),
        'd_e_n_g_l_u': '\u767b\u5f55'.encode('utf-8'),
        'q_u_e_d_i_n_g': '\u786e\u5b9a'.encode('utf-8'),
        'g_u_a_n_b_i': '\u5173\u95ed'.encode('utf-8'),
        't_i_a_o_g_u_o': '\u8df3\u8fc7'.encode('utf-8'),
    }
    print('FILE:', path, 'size:', len(raw))
    for word, b in targets.items():
        cnt = raw.count(b)
        print('  ', word, '->', cnt, 'occurrences')
    txt = raw.decode('utf-8', errors='replace')
    bad = [i+1 for i,l in enumerate(txt.split('\n')) if 'has-text(' in l and '??' in l]
    print('  has-text lines with ?? :', bad[:10])
    return txt

for p in sys.argv[1:]:
    analyze(p)
