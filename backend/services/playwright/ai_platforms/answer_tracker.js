// Auto-generated answer tracker for Playwright page.evaluate
// Called as: ([timeoutMs, stableChecks, checkIntervalMs, question]) => { ... }
([timeoutMs, stableChecks, checkIntervalMs, question]) => {
    return new Promise((resolve) => {
        const startTime = Date.now();
        let lastText = '';
        let stableCount = 0;
        let fastForward = false;

        // \u2500\u2500 \u9009\u62E9\u5668\u5217\u8868\uFF08\u4F18\u5148\u7EA7\u4ECE\u9AD8\u5230\u4F4E\uFF09\u2500\u2500
        // \u4F18\u5148\u627E\u6D88\u606F\u5BB9\u5668\uFF0C\u518D\u627E\u901A\u7528\u5185\u5BB9\u533A
        const SELECTOR_GROUPS = [
            // \u8C46\u5305/\u901A\u4E49\u5343\u95EE/DeepSeek \u5E38\u89C1\u56DE\u7B54\u5BB9\u5668
            '[class*="message-card"]',
            '[class*="bubble-content"]',
            '[class*="chat-message"]',
            '[class*="assistant"]',
            '[class*="answer"]',
            '[class*="response"]',
            '[class*="result"]',
            // \u901A\u7528 Markdown \u5185\u5BB9
            '[class*="markdown-body"]',
            '[class*="md-content"]',
            '[class*="prose"]',
            // \u901A\u7528\u5185\u5BB9\u5757
            'div[class*="content"]',
            'div[class*="text"]',
            'div[class*="message"]',
        ];

        function scanPage() {
            // 1. \u4F18\u5148\u7528\u7279\u5B9A\u9009\u62E9\u5668\u7EC4\u627E\u6700\u65B0\u56DE\u7B54
            for (const group of SELECTOR_GROUPS) {
                const elements = document.querySelectorAll(group);
                if (!elements.length) continue;
                // \u53D6\u6700\u540E\u4E00\u4E2A\uFF08\u901A\u5E38\u662F\u6700\u65B0\u56DE\u7B54\uFF09
                for (let i = elements.length - 1; i >= 0; i--) {
                    const el = elements[i];
                    if (el.offsetParent === null) continue;
                    const s = window.getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden') continue;
                    const text = (el.innerText || el.textContent || '').trim();
                    if (text.length < 50) continue;
                    if (text.length > 15000) continue;
                    // \u8DF3\u8FC7\u7EAF UI \u5143\u7D20
                    if (looksLikeUIElement(text)) continue;
                    return { text, selector: group };
                }
            }
            // 2. \u5168\u9875\u626B\u63CF\uFF08\u515C\u5E95\uFF09
            const allSelectors = 'div, p, section, article, span';
            let best = { text: '', selector: '' };
            document.querySelectorAll(allSelectors).forEach(function(el) {
                if (el.offsetParent === null) return;
                const s = window.getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden') return;
                const text = (el.innerText || el.textContent || '').trim();
                if (text.length < 80) return;
                if (text === question) return;
                if (text.length > 15000) return;
                if (looksLikeUIElement(text)) return;
                if (text.length > best.text.length) {
                    best = { text, selector: el.className || el.tagName };
                }
            });
            return best.text ? best : null;
        }

        function looksLikeUIElement(text) {
            if (!text || text.length < 5) return true;
            // \u68C0\u6D4B\u662F\u5426\u4E3A\u7EAF UI \u6309\u94AE/\u83DC\u5355\u5217\u8868
            const lines = text.split('\n').filter(function(l) { return l.trim().length > 0; });
            if (lines.length >= 3) {
                // \u8D85\u8FC7 70% \u662F\u77ED\u884C\uFF08< 30\u5B57\uFF09\u4E14\u65E0\u53E5\u53F7\u7ED3\u5C3E \u2192 \u7591\u4F3C\u83DC\u5355/\u63a8\u8350\u5217\u8868
                const shortNoPeriod = lines.filter(function(l) {
                    const t = l.trim();
                    return t.length < 30 && t.slice(-1) !== '\u3002' && t.slice(-1) !== '\uFF01' && t.slice(-1) !== '\uFF1F' && t.slice(-1) !== '.';
                });
                if (shortNoPeriod.length / lines.length >= 0.7) return true;
            }
            return false;
        }

        function looksLikeRealAnswer(text) {
            if (!text || text.length < 80) return false;
            if (text === question) return false;
            if (looksLikeUIElement(text)) return false;
            // \u68C0\u6D4B\u641C\u7D22\u63a8\u8350\u98CE\u683C\uFF08\u77ED\u884C\u5217\u8868 + \u542B\u63a8\u8350\u5173\u952E\u8BCD\uFF09
            const lines = text.split('\n').filter(function(l) { return l.trim().length > 0; });
            if (lines.length >= 3) {
                const shortNoPeriod = lines.filter(function(l) {
                    const t = l.trim();
                    return t.length < 40 && t.slice(-1) !== '\u3002' && t.slice(-1) !== '\uFF01' && t.slice(-1) !== '\uFF1F' && t.slice(-1) !== '.';
                });
                if (shortNoPeriod.length / lines.length >= 0.7) {
                    // \u542B\u63a8\u8350\u5173\u952E\u8BCD
                    const recommendationKws = ['\u63a8\u8350', '\u6307\u5357', '\u6392\u540d', '\u9009\u578B', '\u54EA\u5BB6\u597D', '\u600E\u4E48\u9009', '\u5382\u5BB6', '\u670D\u52A1\u5546'];
                    for (const kw of recommendationKws) {
                        if (text.indexOf(kw) >= 0) return false;
                    }
                }
            }
            // \u957F\u6587\u672C\u4F46\u51E0\u4E4E\u6CA1\u6709\u4E2D\u6587\u6807\u70B9 \u2192 \u7591\u4F3C\u4EE3\u7801/\u975E\u81EA\u7136\u8BED\u8A00
            if (text.length > 150) {
                let punctCount = 0;
                for (const p of '\u3002\uFF0C\uFF01\uFF1F\uFF1B\uFF1A\u3001') { punctCount += (text.match(new RegExp(p, 'g')) || []).length; }
                if (punctCount < 2) return false;
            }
            return true;
        }

        var observer = new MutationObserver(function() {
            fastForward = true;
        });
        try {
            observer.observe(document.body, {
                childList: true, subtree: true, characterData: true,
            });
        } catch(e) { /* ignore */ }

        // \u521D\u59CB\u626B\u63CF\uFF08\u53EF\u80FD\u9875\u9762\u5DF2\u6709\u5185\u5BB9\uFF09
        var initial = scanPage();
        if (initial && looksLikeRealAnswer(initial.text)) {
            lastText = initial.text;
            stableCount = 1;
        }

        var timer = setInterval(function() {
            var result = scanPage();

            if (result && looksLikeRealAnswer(result.text)) {
                if (result.text === lastText) {
                    stableCount = stableCount + 1;
                    if (stableCount >= stableChecks) {
                        clearInterval(timer);
                        observer.disconnect();
                        resolve({
                            success: true,
                            answer: result.text.substring(0, 5000),
                            selector: result.selector,
                            length: result.text.length,
                            method: 'polling-stable',
                        });
                        return;
                    }
                } else {
                    lastText = result.text;
                    stableCount = 1;
                }
            } else if (result && !looksLikeRealAnswer(result.text)) {
                lastText = '';
                stableCount = 0;
            }

            if (fastForward) {
                fastForward = false;
                var quick = scanPage();
                if (quick && looksLikeRealAnswer(quick.text) && quick.text.length > (lastText ? lastText.length : 0)) {
                    lastText = quick.text;
                    stableCount = 1;
                }
            }

            if (Date.now() - startTime > timeoutMs) {
                clearInterval(timer);
                observer.disconnect();
                // \u8D85\u65F6\u65F6\u8FD4\u56DE\u5DF2\u627E\u5230\u7684\u6700\u4F73\u5019\u9009\uFF08\u5373\u4F7F\u4E0D\u5B8C\u5168\u7A33\u5B9A\uFF09
                if (lastText && looksLikeRealAnswer(lastText)) {
                    resolve({
                        success: true,
                        answer: lastText.substring(0, 5000),
                        selector: 'polling-timeout',
                        length: lastText.length,
                        method: 'polling-timeout',
                    });
                } else if (result && result.text.length > 80) {
                    // \u5C1D\u8BD5\u8FD4\u56DE\u627E\u5230\u7684\u6700\u957F\u6587\u672C
                    resolve({
                        success: true,
                        answer: result.text.substring(0, 5000),
                        selector: result.selector,
                        length: result.text.length,
                        method: 'polling-final',
                    });
                } else {
                    resolve(null);
                }
            }
        }, checkIntervalMs);
    });
}
