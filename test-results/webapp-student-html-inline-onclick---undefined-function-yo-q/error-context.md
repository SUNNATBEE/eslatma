# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: webapp.spec.js >> student.html >> inline onclick - undefined function yo'q
- Location: e2e-tests\webapp.spec.js:205:5

# Error details

```
Error: expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 3

- Array []
+ Array [
+   "if",
+ ]
```

# Test source

```ts
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
  176 |       expect(Math.abs(diffDivs)).toBeLessThan(5); // 5 tadan ko'p bo'lsa xato
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
> 237 |       expect(uniqueMissing).toEqual([]);
      |                             ^ Error: expect(received).toEqual(expected) // deep equality
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
  277 |     test('console.log qoldiqlari', async ({ page }) => {
  278 |       const html = fs.readFileSync(filePath, 'utf-8');
  279 |       const consoleLogs = (html.match(/console\.(log|debug|info)\(/g) || []);
  280 |       if (consoleLogs.length > 10) {
  281 |         console.log(`KO'P CONSOLE.LOG (${htmlFile}): ${consoleLogs.length} ta`);
  282 |       }
  283 |     });
  284 | 
  285 |     test('XSS - innerHTML bilan foydalanuvchi ma\'lumotlari', async ({ page }) => {
  286 |       const html = fs.readFileSync(filePath, 'utf-8');
  287 | 
  288 |       // innerHTML = ... (potential XSS)
  289 |       const innerHTMLAssigns = html.match(/\.innerHTML\s*[+]?=/g) || [];
  290 | 
  291 |       // textContent yoki innerText ishlatish yaxshiroq
  292 |       if (innerHTMLAssigns.length > 30) {
  293 |         console.log(`KO'P innerHTML (${htmlFile}): ${innerHTMLAssigns.length} ta - XSS xavfi bor`);
  294 |       }
  295 |     });
  296 | 
  297 |   });
  298 | }
  299 | 
  300 | // API endpoint testlar - main.py dagi endpointlarni tekshirish
  301 | test.describe('API endpoint validation', () => {
  302 |   test('main.py dagi barcha API endpointlar webapp da ishlatilgan', async () => {
  303 |     const mainPy = fs.readFileSync(path.resolve(__dirname, '..', 'main.py'), 'utf-8');
  304 | 
  305 |     // API endpointlarni topish
  306 |     const apiRoutes = mainPy.match(/app\.router\.add_(get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']/g) || [];
  307 |     const endpoints = apiRoutes.map(r => {
  308 |       const m = r.match(/["']([^"']+)["']/);
  309 |       return m ? m[1] : null;
  310 |     }).filter(Boolean);
  311 | 
  312 |     console.log(`Jami API endpointlar: ${endpoints.length}`);
  313 | 
  314 |     // Foydalanilmagan endpointlarni topish
  315 |     const allWebappCode = htmlFiles
  316 |       .map(f => {
  317 |         const p = path.join(WEBAPP_DIR, f);
  318 |         return fs.existsSync(p) ? fs.readFileSync(p, 'utf-8') : '';
  319 |       })
  320 |       .join('\n');
  321 | 
  322 |     const unusedEndpoints = endpoints.filter(ep => {
  323 |       const epPath = ep.replace(/\{[^}]+\}/g, ''); // remove path params
  324 |       return !allWebappCode.includes(epPath) && ep.startsWith('/api/');
  325 |     });
  326 | 
  327 |     if (unusedEndpoints.length > 0) {
  328 |       console.log('API endpointlar webapp da ishlatilmagan (bu normal bo\'lishi mumkin - bot orqali ishlatiladi):');
  329 |       unusedEndpoints.forEach(ep => console.log('  -', ep));
  330 |     }
  331 |   });
  332 | });
  333 | 
```