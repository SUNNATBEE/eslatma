/**
 * Mini App e2e uchun Telegram va tashqi CDN stublari.
 */

const TG_MOCK_SCRIPT = `
  window.Telegram = {
    WebApp: {
      initData: 'mock_init_data_hash',
      initDataUnsafe: { user: { id: 123456789, first_name: 'Test', username: 'testuser' } },
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

const GSAP_STUB = `
  window.gsap = {
    to: function(){},
    from: function(){},
    fromTo: function(){ return { duration: function(){ return this; }, ease: function(){ return this; }, stagger: function(){ return this; }, delay: function(){ return this; }, repeat: function(){ return this; }, yoyo: function(){ return this; }, clearProps: function(){ return this; }, overwrite: function(){ return this; }, onComplete: function(){ return this; }, killTweensOf: function(){} }; },
    set: function(){},
    timeline: function(){ return { to: function(){ return this; }, from: function(){ return this; }, play: function(){}, kill: function(){} }; },
    registerPlugin: function(){},
    killTweensOf: function(){},
  };
`;

async function setupTelegramAndCdnRoutes(page) {
  await page.route('**/telegram-web-app.js', (route) => {
    route.fulfill({
      contentType: 'text/javascript',
      body: '// stub\nwindow.Telegram = window.Telegram || {};\n',
    });
  });
  await page.route('**/gsap.min.js', (route) => route.fulfill({ contentType: 'text/javascript', body: GSAP_STUB }));
  await page.route('**/ScrollTrigger.min.js', (route) =>
    route.fulfill({ contentType: 'text/javascript', body: 'try{window.gsap&&window.gsap.registerPlugin();}catch(e){}' }),
  );
  await page.route('**/chess.min.js', (route) =>
    route.fulfill({
      contentType: 'text/javascript',
      body: 'window.Chess=function(){this.moves=function(){return[]};this.move=function(){return null};this.fen=function(){return""};this.game_over=function(){return false};this.in_checkmate=function(){return false};this.in_draw=function(){return false};this.in_stalemate=function(){return false};this.turn=function(){return"w"};this.reset=function(){};this.undo=function(){};this.board=function(){return[]};this.ascii=function(){return""};};',
    }),
  );
  await page.route('**/lottie.min.js', (route) =>
    route.fulfill({
      contentType: 'text/javascript',
      body: 'window.lottie={loadAnimation:function(){return{play:function(){},stop:function(){},destroy:function(){}}};};',
    }),
  );
  await page.route('**/confetti.browser.min.js', (route) =>
    route.fulfill({ contentType: 'text/javascript', body: 'window.confetti=function(){};' }),
  );
  await page.route('**/fonts.googleapis.com/**', (route) => route.fulfill({ contentType: 'text/css', body: '/* noop */' }));
  await page.route('**/fonts.gstatic.com/**', (route) => route.fulfill({ status: 200, body: '' }));
  await page.route('**/cdnjs.cloudflare.com/**', (route) => {
    const u = route.request().url();
    if (u.includes('chess')) {
      return route.fulfill({
        contentType: 'text/javascript',
        body: 'window.Chess=function(){};',
      });
    }
    return route.fulfill({ contentType: 'text/javascript', body: '' });
  });
  await page.addInitScript(TG_MOCK_SCRIPT);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

module.exports = { TG_MOCK_SCRIPT, setupTelegramAndCdnRoutes, sleep };
