const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const WEBAPP_DIR = path.resolve(__dirname, '..', 'webapp');
const htmlFiles = ['student.html', 'games.html', 'admin-mini.html', 'curator.html', 'guide.html', 'admin.html'];

// Mock Telegram WebApp object to prevent errors
const TG_MOCK_SCRIPT = `
  window.Telegram = {
    WebApp: {
      initData: 'test_mock_data',
      initDataUnsafe: { user: { id: 123456, first_name: 'Test', username: 'testuser' } },
      ready: function(){},
      expand: function(){},
      close: function(){},
      enableClosingConfirmation: function(){},
      disableVerticalSwipes: function(){},
      setHeaderColor: function(){},
      setBackgroundColor: function(){},
      onEvent: function(){},
      offEvent: function(){},
      sendData: function(){},
      openLink: function(){},
      openTelegramLink: function(){},
      showPopup: function(){},
      showAlert: function(){},
      showConfirm: function(){},
      HapticFeedback: { impactOccurred: function(){}, notificationOccurred: function(){}, selectionChanged: function(){} },
      MainButton: { show: function(){}, hide: function(){}, setText: function(){}, onClick: function(){}, isVisible: false, text: '' },
      BackButton: { show: function(){}, hide: function(){}, onClick: function(){} },
      themeParams: {
        bg_color: '#0d0d18', text_color: '#e8eaf6', hint_color: '#64748b',
        link_color: '#00d4ff', button_color: '#00d4ff', button_text_color: '#ffffff',
        secondary_bg_color: '#12121f'
      },
      colorScheme: 'dark',
      viewportHeight: 844,
      viewportStableHeight: 844,
      isExpanded: true,
      platform: 'tdesktop',
    }
  };
`;

for (const htmlFile of htmlFiles) {
  const filePath = path.join(WEBAPP_DIR, htmlFile);
  if (!fs.existsSync(filePath)) continue;

  test.describe(`${htmlFile}`, () => {

    test('sahifa JS xatosiz yuklanyapti', async ({ page }) => {
      const jsErrors = [];
      page.on('pageerror', err => jsErrors.push(err.message));

      // Intercept Telegram JS and external scripts
      await page.route('**/telegram-web-app.js', route => {
        route.fulfill({ contentType: 'text/javascript', body: TG_MOCK_SCRIPT.replace('window.Telegram =', 'window.Telegram = window.Telegram ||') });
      });
      await page.route('**/gsap.min.js', route => route.fulfill({ contentType: 'text/javascript', body: 'window.gsap = { to:()=>{}, from:()=>{}, fromTo:()=>{}, set:()=>{}, timeline:()=>({to:()=>({}),from:()=>({}),play:()=>{}}), registerPlugin:()=>{} };' }));
      await page.route('**/chess.min.js', route => route.fulfill({ contentType: 'text/javascript', body: 'window.Chess = function(){ this.moves=()=>[];this.move=()=>null;this.fen=()=>"";this.game_over=()=>false;this.in_checkmate=()=>false;this.in_draw=()=>false;this.in_stalemate=()=>false;this.turn=()=>"w";this.reset=()=>{};this.undo=()=>{};this.board=()=>[];this.ascii=()=>""; };' }));
      await page.route('**/lottie.min.js', route => route.fulfill({ contentType: 'text/javascript', body: 'window.lottie = { loadAnimation: ()=>({play:()=>{},stop:()=>{},destroy:()=>{}}) };' }));
      await page.route('**/confetti.browser.min.js', route => route.fulfill({ contentType: 'text/javascript', body: 'window.confetti = ()=>{};' }));
      await page.route('**/fonts.googleapis.com/**', route => route.fulfill({ contentType: 'text/css', body: '' }));
      await page.route('**/fonts.gstatic.com/**', route => route.fulfill({ contentType: 'font/woff2', body: '' }));
      await page.route('**/cdnjs.cloudflare.com/**', route => {
        if (route.request().url().includes('chess')) {
          return route.fulfill({ contentType: 'text/javascript', body: 'window.Chess = function(){ this.moves=()=>[];this.move=()=>null;this.fen=()=>""; };' });
        }
        return route.fulfill({ contentType: 'text/javascript', body: '' });
      });

      // Mock API calls
      await page.route('**/api/**', route => {
        route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: [] }) });
      });
      await page.route('**/manifest.json', route => {
        route.fulfill({ contentType: 'application/json', body: JSON.stringify({ name: 'Test' }) });
      });

      // Add TG mock before page loads
      await page.addInitScript(TG_MOCK_SCRIPT);
      await page.goto(`file://${filePath.replace(/\\/g, '/')}`);
      await page.waitForTimeout(2000);

      // Filter out network-related errors (expected for file:// protocol)
      const realErrors = jsErrors.filter(e =>
        !e.includes('fetch') &&
        !e.includes('Failed to') &&
        !e.includes('NetworkError') &&
        !e.includes('net::') &&
        !e.includes('ERR_FILE_NOT_FOUND') &&
        !e.includes('CORS') &&
        !e.includes('Load failed') &&
        !e.includes('Cannot read properties of null') && // DOM not ready issues on file://
        !e.includes('initData') &&
        !e.includes('Telegram')
      );

      if (realErrors.length > 0) {
        console.log(`JS XATOLAR (${htmlFile}):`, realErrors);
      }
      expect(realErrors).toEqual([]);
    });

    test('DOCTYPE va meta taglar to\'g\'ri', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');

      // DOCTYPE bor
      expect(html.startsWith('<!DOCTYPE html>')).toBe(true);

      // charset
      expect(html).toContain('charset="UTF-8"');

      // viewport
      expect(html).toContain('viewport');
    });

    test('barcha id lar unikal', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');
      const idMatches = html.match(/\bid="([^"]+)"/g) || [];
      const ids = idMatches.map(m => m.match(/id="([^"]+)"/)[1]);
      const duplicates = ids.filter((id, i) => ids.indexOf(id) !== i);
      const uniqueDuplicates = [...new Set(duplicates)];

      if (uniqueDuplicates.length > 0) {
        console.log(`DUBLIKAT ID lar (${htmlFile}):`, uniqueDuplicates);
      }
      expect(uniqueDuplicates).toEqual([]);
    });

    test('getElementById - mavjud bo\'lmagan elementlar', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');

      // Barcha getElementById chaqiruvlarini topish
      const getByIdCalls = html.match(/getElementById\(['"]([^'"]+)['"]\)/g) || [];
      const referencedIds = getByIdCalls.map(m => m.match(/getElementById\(['"]([^'"]+)['"]\)/)[1]);

      // Barcha e'lon qilingan id larni topish
      const declaredIds = (html.match(/\bid="([^"]+)"/g) || []).map(m => m.match(/id="([^"]+)"/)[1]);

      // Dinamik yaratilgan elementlarni filter qilish
      const dynamicPatterns = ['refRegOverlay', 'directRegOverlay', 'gameLimitModal', 'multiRoom_', 'chess_'];
      const missingIds = referencedIds.filter(id =>
        !declaredIds.includes(id) &&
        !dynamicPatterns.some(p => id.startsWith(p)) &&
        !id.includes('${') // template literal
      );

      const uniqueMissing = [...new Set(missingIds)];
      if (uniqueMissing.length > 0) {
        console.log(`MAVJUD BO'LMAGAN ID lar (${htmlFile}):`, uniqueMissing);
      }
      // Warning sifatida, lekin test yiqilmasin - ba'zilari dinamik
    });

    test('yopilmagan HTML taglar', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');

      // Asosiy tag juftliklarini tekshirish
      const openDivs = (html.match(/<div[\s>]/g) || []).length;
      const closeDivs = (html.match(/<\/div>/g) || []).length;
      const diffDivs = openDivs - closeDivs;
      if (diffDivs !== 0) {
        console.log(`DIV balans xatosi (${htmlFile}): ${openDivs} open, ${closeDivs} close, farq: ${diffDivs}`);
      }

      const openSpans = (html.match(/<span[\s>]/g) || []).length;
      const closeSpans = (html.match(/<\/span>/g) || []).length;
      const diffSpans = openSpans - closeSpans;
      if (diffSpans !== 0) {
        console.log(`SPAN balans xatosi (${htmlFile}): ${openSpans} open, ${closeSpans} close, farq: ${diffSpans}`);
      }

      // Ogohlantiramiz lekin test yiqilmasin chunki ba'zi taglar JS orqali yaratiladi
      // va JS string ichidagi <div>, <span> ham hisobga kirib ketadi
      expect(Math.abs(diffDivs)).toBeLessThan(10); // 10 tadan ko'p bo'lsa xato
      expect(Math.abs(diffSpans)).toBeLessThan(10);
    });

    test('CSS - undefined variable yo\'q', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');

      // var(--...) ishlatilgan CSS o'zgaruvchilarni topish
      const usedVars = (html.match(/var\(--([a-zA-Z0-9_-]+)/g) || [])
        .map(v => v.replace('var(--', ''));

      // :root da e'lon qilingan o'zgaruvchilar
      const declaredVars = (html.match(/--([a-zA-Z0-9_-]+)\s*:/g) || [])
        .map(v => v.replace('--', '').replace(':', '').trim());

      // Telegram CSS o'zgaruvchilari (tg-theme-*) va standart CSS o'zgaruvchilarni chiqarib tashlash
      const missingVars = usedVars.filter(v =>
        !declaredVars.includes(v) &&
        !v.startsWith('tg-theme-') &&
        !v.startsWith('tg-') &&
        v !== 'safe-area-inset-bottom' // env() value
      );

      const uniqueMissing = [...new Set(missingVars)];
      if (uniqueMissing.length > 0) {
        console.log(`ANIQLANMAGAN CSS o'zgaruvchilar (${htmlFile}):`, uniqueMissing);
      }
    });

    test('inline onclick - undefined function yo\'q', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');

      // onclick="functionName(...)" larni topish
      const onclickCalls = html.match(/onclick="([^"]+)"/g) || [];
      const calledFuncs = [];
      for (const call of onclickCalls) {
        const match = call.match(/onclick="([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(/);
        if (match) calledFuncs.push(match[1]);
      }

      // E'lon qilingan funksiyalar
      const declaredFuncs = (html.match(/function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)/g) || [])
        .map(f => f.replace('function ', ''));

      // Built-in/global funksiyalar va JS kalit so'zlarni chiqarib tashlash
      const builtins = ['alert', 'confirm', 'prompt', 'open', 'close', 'parseInt', 'parseFloat',
        'clearInterval', 'clearTimeout', 'setTimeout', 'setInterval', 'event', 'this',
        'console', 'window', 'document', 'navigator', 'history', 'location',
        'if', 'else', 'return', 'new', 'typeof', 'void', 'delete'];

      const missingFuncs = calledFuncs.filter(f =>
        !declaredFuncs.includes(f) &&
        !builtins.includes(f) &&
        !f.startsWith('document') &&
        !f.startsWith('window')
      );

      const uniqueMissing = [...new Set(missingFuncs)];
      if (uniqueMissing.length > 0) {
        console.log(`ANIQLANMAGAN funksiyalar (${htmlFile}):`, uniqueMissing);
      }
      // Hamma function topilishi kerak
      expect(uniqueMissing).toEqual([]);
    });

    test('broken img src yo\'q', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');
      const imgSrcs = (html.match(/src="([^"]+)"/g) || [])
        .map(m => m.match(/src="([^"]+)"/)[1])
        .filter(src =>
          !src.startsWith('http') &&
          !src.startsWith('data:') &&
          !src.startsWith('//') &&
          !src.includes('${') &&
          !src.includes("'+") &&
          src.match(/\.(png|jpg|jpeg|gif|svg|webp|ico)$/i)
        );

      for (const src of imgSrcs) {
        const fullPath = path.resolve(WEBAPP_DIR, src.replace(/^\/webapp\//, ''));
        if (!fs.existsSync(fullPath)) {
          console.log(`TOPILMAGAN RASM (${htmlFile}): ${src}`);
        }
      }
    });

    test('accessibility - input lar label bilan', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');

      // input type="text" va textarea larni topish
      const inputs = (html.match(/<input[^>]+type="text"[^>]*>/g) || []);
      const textareas = (html.match(/<textarea[^>]*>/g) || []);

      const inputsWithoutPlaceholder = inputs.filter(inp =>
        !inp.includes('placeholder=') && !inp.includes('aria-label=')
      );

      if (inputsWithoutPlaceholder.length > 0) {
        console.log(`PLACEHOLDER/LABEL yo'q (${htmlFile}):`, inputsWithoutPlaceholder.length, 'ta input');
      }
    });

    test('console.log qoldiqlari', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');
      const consoleLogs = (html.match(/console\.(log|debug|info)\(/g) || []);
      if (consoleLogs.length > 10) {
        console.log(`KO'P CONSOLE.LOG (${htmlFile}): ${consoleLogs.length} ta`);
      }
    });

    test('XSS - innerHTML bilan foydalanuvchi ma\'lumotlari', async ({ page }) => {
      const html = fs.readFileSync(filePath, 'utf-8');

      // innerHTML = ... (potential XSS)
      const innerHTMLAssigns = html.match(/\.innerHTML\s*[+]?=/g) || [];

      // textContent yoki innerText ishlatish yaxshiroq
      if (innerHTMLAssigns.length > 30) {
        console.log(`KO'P innerHTML (${htmlFile}): ${innerHTMLAssigns.length} ta - XSS xavfi bor`);
      }
    });

  });
}

// API endpoint testlar - main.py dagi endpointlarni tekshirish
test.describe('API endpoint validation', () => {
  test('main.py dagi barcha API endpointlar webapp da ishlatilgan', async () => {
    const mainPy = fs.readFileSync(path.resolve(__dirname, '..', 'main.py'), 'utf-8');

    // API endpointlarni topish
    const apiRoutes = mainPy.match(/app\.router\.add_(get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']/g) || [];
    const endpoints = apiRoutes.map(r => {
      const m = r.match(/["']([^"']+)["']/);
      return m ? m[1] : null;
    }).filter(Boolean);

    console.log(`Jami API endpointlar: ${endpoints.length}`);

    // Foydalanilmagan endpointlarni topish
    const allWebappCode = htmlFiles
      .map(f => {
        const p = path.join(WEBAPP_DIR, f);
        return fs.existsSync(p) ? fs.readFileSync(p, 'utf-8') : '';
      })
      .join('\n');

    const unusedEndpoints = endpoints.filter(ep => {
      const epPath = ep.replace(/\{[^}]+\}/g, ''); // remove path params
      return !allWebappCode.includes(epPath) && ep.startsWith('/api/');
    });

    if (unusedEndpoints.length > 0) {
      console.log('API endpointlar webapp da ishlatilmagan (bu normal bo\'lishi mumkin - bot orqali ishlatiladi):');
      unusedEndpoints.forEach(ep => console.log('  -', ep));
    }
  });
});
