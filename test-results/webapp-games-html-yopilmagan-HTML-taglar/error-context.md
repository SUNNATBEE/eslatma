# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: webapp.spec.js >> games.html >> yopilmagan HTML taglar
- Location: e2e-tests\webapp.spec.js:157:5

# Error details

```
Error: expect(received).toBeLessThan(expected)

Expected: < 5
Received:   6
```

# Test source

```ts
  76  |       });
  77  |       await page.route('**/manifest.json', route => {
  78  |         route.fulfill({ contentType: 'application/json', body: JSON.stringify({ name: 'Test' }) });
  79  |       });
  80  | 
  81  |       // Add TG mock before page loads
  82  |       await page.addInitScript(TG_MOCK_SCRIPT);
  83  |       await page.goto(`file://${filePath.replace(/\\/g, '/')}`);
  84  |       await page.waitForTimeout(2000);
  85  | 
  86  |       // Filter out network-related errors (expected for file:// protocol)
  87  |       const realErrors = jsErrors.filter(e =>
  88  |         !e.includes('fetch') &&
  89  |         !e.includes('Failed to') &&
  90  |         !e.includes('NetworkError') &&
  91  |         !e.includes('net::') &&
  92  |         !e.includes('ERR_FILE_NOT_FOUND') &&
  93  |         !e.includes('CORS') &&
  94  |         !e.includes('Load failed') &&
  95  |         !e.includes('Cannot read properties of null') && // DOM not ready issues on file://
  96  |         !e.includes('initData') &&
  97  |         !e.includes('Telegram')
  98  |       );
  99  | 
  100 |       if (realErrors.length > 0) {
  101 |         console.log(`JS XATOLAR (${htmlFile}):`, realErrors);
  102 |       }
  103 |       expect(realErrors).toEqual([]);
  104 |     });
  105 | 
  106 |     test('DOCTYPE va meta taglar to\'g\'ri', async ({ page }) => {
  107 |       const html = fs.readFileSync(filePath, 'utf-8');
  108 | 
  109 |       // DOCTYPE bor
  110 |       expect(html.startsWith('<!DOCTYPE html>')).toBe(true);
  111 | 
  112 |       // charset
  113 |       expect(html).toContain('charset="UTF-8"');
  114 | 
  115 |       // viewport
  116 |       expect(html).toContain('viewport');
  117 |     });
  118 | 
  119 |     test('barcha id lar unikal', async ({ page }) => {
  120 |       const html = fs.readFileSync(filePath, 'utf-8');
  121 |       const idMatches = html.match(/\bid="([^"]+)"/g) || [];
  122 |       const ids = idMatches.map(m => m.match(/id="([^"]+)"/)[1]);
  123 |       const duplicates = ids.filter((id, i) => ids.indexOf(id) !== i);
  124 |       const uniqueDuplicates = [...new Set(duplicates)];
  125 | 
  126 |       if (uniqueDuplicates.length > 0) {
  127 |         console.log(`DUBLIKAT ID lar (${htmlFile}):`, uniqueDuplicates);
  128 |       }
  129 |       expect(uniqueDuplicates).toEqual([]);
  130 |     });
  131 | 
  132 |     test('getElementById - mavjud bo\'lmagan elementlar', async ({ page }) => {
  133 |       const html = fs.readFileSync(filePath, 'utf-8');
  134 | 
  135 |       // Barcha getElementById chaqiruvlarini topish
  136 |       const getByIdCalls = html.match(/getElementById\(['"]([^'"]+)['"]\)/g) || [];
  137 |       const referencedIds = getByIdCalls.map(m => m.match(/getElementById\(['"]([^'"]+)['"]\)/)[1]);
  138 | 
  139 |       // Barcha e'lon qilingan id larni topish
  140 |       const declaredIds = (html.match(/\bid="([^"]+)"/g) || []).map(m => m.match(/id="([^"]+)"/)[1]);
  141 | 
  142 |       // Dinamik yaratilgan elementlarni filter qilish
  143 |       const dynamicPatterns = ['refRegOverlay', 'directRegOverlay', 'gameLimitModal', 'multiRoom_', 'chess_'];
  144 |       const missingIds = referencedIds.filter(id =>
  145 |         !declaredIds.includes(id) &&
  146 |         !dynamicPatterns.some(p => id.startsWith(p)) &&
  147 |         !id.includes('${') // template literal
  148 |       );
  149 | 
  150 |       const uniqueMissing = [...new Set(missingIds)];
  151 |       if (uniqueMissing.length > 0) {
  152 |         console.log(`MAVJUD BO'LMAGAN ID lar (${htmlFile}):`, uniqueMissing);
  153 |       }
  154 |       // Warning sifatida, lekin test yiqilmasin - ba'zilari dinamik
  155 |     });
  156 | 
  157 |     test('yopilmagan HTML taglar', async ({ page }) => {
  158 |       const html = fs.readFileSync(filePath, 'utf-8');
  159 | 
  160 |       // Asosiy tag juftliklarini tekshirish
  161 |       const openDivs = (html.match(/<div[\s>]/g) || []).length;
  162 |       const closeDivs = (html.match(/<\/div>/g) || []).length;
  163 |       const diffDivs = openDivs - closeDivs;
  164 |       if (diffDivs !== 0) {
  165 |         console.log(`DIV balans xatosi (${htmlFile}): ${openDivs} open, ${closeDivs} close, farq: ${diffDivs}`);
  166 |       }
  167 | 
  168 |       const openSpans = (html.match(/<span[\s>]/g) || []).length;
  169 |       const closeSpans = (html.match(/<\/span>/g) || []).length;
  170 |       const diffSpans = openSpans - closeSpans;
  171 |       if (diffSpans !== 0) {
  172 |         console.log(`SPAN balans xatosi (${htmlFile}): ${openSpans} open, ${closeSpans} close, farq: ${diffSpans}`);
  173 |       }
  174 | 
  175 |       // Ogohlantiramiz lekin test yiqilmasin chunki ba'zi taglar JS orqali yaratiladi
> 176 |       expect(Math.abs(diffDivs)).toBeLessThan(5); // 5 tadan ko'p bo'lsa xato
      |                                  ^ Error: expect(received).toBeLessThan(expected)
  177 |       expect(Math.abs(diffSpans)).toBeLessThan(5);
  178 |     });
  179 | 
  180 |     test('CSS - undefined variable yo\'q', async ({ page }) => {
  181 |       const html = fs.readFileSync(filePath, 'utf-8');
  182 | 
  183 |       // var(--...) ishlatilgan CSS o'zgaruvchilarni topish
  184 |       const usedVars = (html.match(/var\(--([a-zA-Z0-9_-]+)/g) || [])
  185 |         .map(v => v.replace('var(--', ''));
  186 | 
  187 |       // :root da e'lon qilingan o'zgaruvchilar
  188 |       const declaredVars = (html.match(/--([a-zA-Z0-9_-]+)\s*:/g) || [])
  189 |         .map(v => v.replace('--', '').replace(':', '').trim());
  190 | 
  191 |       // Telegram CSS o'zgaruvchilari (tg-theme-*) va standart CSS o'zgaruvchilarni chiqarib tashlash
  192 |       const missingVars = usedVars.filter(v =>
  193 |         !declaredVars.includes(v) &&
  194 |         !v.startsWith('tg-theme-') &&
  195 |         !v.startsWith('tg-') &&
  196 |         v !== 'safe-area-inset-bottom' // env() value
  197 |       );
  198 | 
  199 |       const uniqueMissing = [...new Set(missingVars)];
  200 |       if (uniqueMissing.length > 0) {
  201 |         console.log(`ANIQLANMAGAN CSS o'zgaruvchilar (${htmlFile}):`, uniqueMissing);
  202 |       }
  203 |     });
  204 | 
  205 |     test('inline onclick - undefined function yo\'q', async ({ page }) => {
  206 |       const html = fs.readFileSync(filePath, 'utf-8');
  207 | 
  208 |       // onclick="functionName(...)" larni topish
  209 |       const onclickCalls = html.match(/onclick="([^"]+)"/g) || [];
  210 |       const calledFuncs = [];
  211 |       for (const call of onclickCalls) {
  212 |         const match = call.match(/onclick="([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(/);
  213 |         if (match) calledFuncs.push(match[1]);
  214 |       }
  215 | 
  216 |       // E'lon qilingan funksiyalar
  217 |       const declaredFuncs = (html.match(/function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)/g) || [])
  218 |         .map(f => f.replace('function ', ''));
  219 | 
  220 |       // Built-in/global funksiyalarni chiqarib tashlash
  221 |       const builtins = ['alert', 'confirm', 'prompt', 'open', 'close', 'parseInt', 'parseFloat',
  222 |         'clearInterval', 'clearTimeout', 'setTimeout', 'setInterval', 'event', 'this',
  223 |         'console', 'window', 'document', 'navigator', 'history', 'location'];
  224 | 
  225 |       const missingFuncs = calledFuncs.filter(f =>
  226 |         !declaredFuncs.includes(f) &&
  227 |         !builtins.includes(f) &&
  228 |         !f.startsWith('document') &&
  229 |         !f.startsWith('window')
  230 |       );
  231 | 
  232 |       const uniqueMissing = [...new Set(missingFuncs)];
  233 |       if (uniqueMissing.length > 0) {
  234 |         console.log(`ANIQLANMAGAN funksiyalar (${htmlFile}):`, uniqueMissing);
  235 |       }
  236 |       // Hamma function topilishi kerak
  237 |       expect(uniqueMissing).toEqual([]);
  238 |     });
  239 | 
  240 |     test('broken img src yo\'q', async ({ page }) => {
  241 |       const html = fs.readFileSync(filePath, 'utf-8');
  242 |       const imgSrcs = (html.match(/src="([^"]+)"/g) || [])
  243 |         .map(m => m.match(/src="([^"]+)"/)[1])
  244 |         .filter(src =>
  245 |           !src.startsWith('http') &&
  246 |           !src.startsWith('data:') &&
  247 |           !src.startsWith('//') &&
  248 |           !src.includes('${') &&
  249 |           !src.includes("'+") &&
  250 |           src.match(/\.(png|jpg|jpeg|gif|svg|webp|ico)$/i)
  251 |         );
  252 | 
  253 |       for (const src of imgSrcs) {
  254 |         const fullPath = path.resolve(WEBAPP_DIR, src.replace(/^\/webapp\//, ''));
  255 |         if (!fs.existsSync(fullPath)) {
  256 |           console.log(`TOPILMAGAN RASM (${htmlFile}): ${src}`);
  257 |         }
  258 |       }
  259 |     });
  260 | 
  261 |     test('accessibility - input lar label bilan', async ({ page }) => {
  262 |       const html = fs.readFileSync(filePath, 'utf-8');
  263 | 
  264 |       // input type="text" va textarea larni topish
  265 |       const inputs = (html.match(/<input[^>]+type="text"[^>]*>/g) || []);
  266 |       const textareas = (html.match(/<textarea[^>]*>/g) || []);
  267 | 
  268 |       const inputsWithoutPlaceholder = inputs.filter(inp =>
  269 |         !inp.includes('placeholder=') && !inp.includes('aria-label=')
  270 |       );
  271 | 
  272 |       if (inputsWithoutPlaceholder.length > 0) {
  273 |         console.log(`PLACEHOLDER/LABEL yo'q (${htmlFile}):`, inputsWithoutPlaceholder.length, 'ta input');
  274 |       }
  275 |     });
  276 | 
```