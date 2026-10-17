(() => {
  const navigation = document.querySelector('[role="navigation"]');
  const settings = document.querySelector('button[data-testid="settings-button"]');
  if (!navigation || !settings) throw new Error('The native sidebar is missing.');
  const navRect = navigation.getBoundingClientRect();
  const settingsRect = settings.getBoundingClientRect();
  const list = [...navigation.children].find(element => getComputedStyle(element).overflowY === 'auto');
  if (navRect.width > 0 && navRect.height > 0) {
    if (!list || list.getBoundingClientRect().height < 80) {
      throw new Error('FAIL: The conversation/project list was collapsed by an injected element.');
    }
    if (settingsRect.bottom < navRect.bottom - 72 || settingsRect.bottom > navRect.bottom) {
      throw new Error(`FAIL: Settings footer overlaps the sidebar content (${Math.round(settingsRect.bottom)} / ${Math.round(navRect.bottom)}).`);
    }
  }
  const widget = document.getElementById('__ag_token_widget');
  const panel = document.getElementById('__ag_token_panel');
  for (const element of [widget, panel]) {
    if (!element || getComputedStyle(element).display === 'none') continue;
    const rect = element.getBoundingClientRect();
    if (rect.left < 0 || rect.top < 0 || rect.right > innerWidth + 1 || rect.bottom > innerHeight + 1) {
      throw new Error('FAIL: Token details extend outside the visible viewport.');
    }
  }
  return {
    verdict: 'PASS',
    sidebarHeight: Math.round(navRect.height),
    listHeight: Math.round(list?.getBoundingClientRect().height || 0),
    settingsBottom: Math.round(settingsRect.bottom),
    viewport: { width: innerWidth, height: innerHeight },
  };
})()
