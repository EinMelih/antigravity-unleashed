const fs = require('fs');
const path = require('path');

// Simple DOM Mocking
class MockNode {
  constructor(tagName, textContent = '', attrs = {}) {
    this.tagName = tagName.toUpperCase();
    this._textContent = textContent;
    this.attrs = attrs;
    this.children = [];
    this.parentElement = null;
    this.clicked = false;
    this.onClick = null;
    this.onScroll = null;
    this.clientHeight = Number(attrs.clientHeight || 0);
    this.scrollHeight = Number(attrs.scrollHeight || 0);
    this._scrollTop = Number(attrs.scrollTop || 0);
  }

  get childNodes() {
    return this.children;
  }

  get textContent() {
    if (this._textContent) return this._textContent;
    return this.children.map(c => c.textContent).join(' ');
  }

  get innerText() {
    return this.textContent;
  }

  get scrollTop() {
    return this._scrollTop;
  }

  set scrollTop(value) {
    this._scrollTop = Number(value || 0);
  }

  dispatchEvent(event) {
    if (event?.type === 'scroll' && this.onScroll) this.onScroll(this._scrollTop);
    return true;
  }

  getAttribute(name) {
    return this.attrs[name] || null;
  }

  getBoundingClientRect() {
    return { top: 100, bottom: 120, left: 10, right: 100, height: 20, width: 90 };
  }

  click() {
    this.clicked = true;
    if (this.onClick) this.onClick();
  }

  closest(selector) {
    let current = this;
    while (current) {
      if (selector === '[role="button"]' && current.getAttribute('role') === 'button') {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  querySelector(selector) {
    const res = this.querySelectorAll(selector);
    return res.length > 0 ? res[0] : null;
  }

  querySelectorAll(selector) {
    const results = [];
    const traverse = (node) => {
      const selectors = selector.split(',').map(s => s.trim().toUpperCase());

      if (selector === 'button[data-project-card="true"]') {
        if (node.tagName === 'BUTTON' && node.getAttribute('data-project-card') === 'true') {
          results.push(node);
        }
      } else if (selector === '[data-testid^="convo-pill-"]') {
        if (String(node.getAttribute('data-testid') || '').startsWith('convo-pill-')) {
          results.push(node);
        }
      } else if (selector === '[data-testid="conversation-row-sidebar"][data-cascade-id]') {
        if (
          node.getAttribute('data-testid') === 'conversation-row-sidebar'
          && node.getAttribute('data-cascade-id')
        ) {
          results.push(node);
        }
      } else if (selector === '[data-testid="conversation-list-sidebar"]') {
        if (node.getAttribute('data-testid') === 'conversation-list-sidebar') {
          results.push(node);
        }
      } else if (selector === 'a[href*="/c/"]') {
        if (node.tagName === 'A' && String(node.getAttribute('href') || '').includes('/c/')) {
          results.push(node);
        }
      } else if (selector === '[data-conversation-id], [data-chat-id]') {
        if (node.getAttribute('data-conversation-id') || node.getAttribute('data-chat-id')) {
          results.push(node);
        }
      } else if (selector === 'svg path') {
        if (node.tagName === 'PATH' && node.parentElement && node.parentElement.tagName === 'SVG') {
          results.push(node);
        }
      } else if (selector === 'svg') {
        if (node.tagName === 'SVG') results.push(node);
      } else if (selector === 'path') {
        if (node.tagName === 'PATH') results.push(node);
      } else if (selector === 'button') {
        if (node.tagName === 'BUTTON') results.push(node);
      } else if (selector === '[data-testid="conversation-archive-button"]') {
        if (node.getAttribute('data-testid') === 'conversation-archive-button') {
          results.push(node);
        }
      } else {
        // Multi-selector support like 'div, span, ...'
        if (selectors.includes(node.tagName)) {
          results.push(node);
        }
      }

      for (const child of node.children) {
        traverse(child);
      }
    };

    for (const child of this.children) {
      traverse(child);
    }
    return results;
  }

  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }
}

const mockDocument = {
  root: new MockNode('BODY'),
  querySelectorAll(selector) {
    const results = [];
    const selectors = selector.split(',').map(s => s.trim().toUpperCase());

    const traverse = (node) => {
      if (selector === 'button[data-project-card="true"]') {
        if (node.tagName === 'BUTTON' && node.getAttribute('data-project-card') === 'true') {
          results.push(node);
        }
      } else if (selector === '[data-testid^="convo-pill-"]') {
        if (String(node.getAttribute('data-testid') || '').startsWith('convo-pill-')) {
          results.push(node);
        }
      } else if (selector === '[data-testid="conversation-row-sidebar"][data-cascade-id]') {
        if (
          node.getAttribute('data-testid') === 'conversation-row-sidebar'
          && node.getAttribute('data-cascade-id')
        ) {
          results.push(node);
        }
      } else if (selector === '[data-testid="conversation-list-sidebar"]') {
        if (node.getAttribute('data-testid') === 'conversation-list-sidebar') {
          results.push(node);
        }
      } else if (selector === 'a[href*="/c/"]') {
        if (node.tagName === 'A' && String(node.getAttribute('href') || '').includes('/c/')) {
          results.push(node);
        }
      } else if (selector === '[data-conversation-id], [data-chat-id]') {
        if (node.getAttribute('data-conversation-id') || node.getAttribute('data-chat-id')) {
          results.push(node);
        }
      } else if (selector === 'button[aria-label="New Conversation in Project"], a[aria-label="New Conversation in Project"]') {
        if (
          (node.tagName === 'BUTTON' || node.tagName === 'A')
          && node.getAttribute('aria-label') === 'New Conversation in Project'
        ) {
          results.push(node);
        }
      } else if (selector === '[data-testid="titlebar-more-actions"]') {
        if (node.getAttribute('data-testid') === 'titlebar-more-actions') {
          results.push(node);
        }
      } else if (selector === '[role="menuitem"]') {
        if (node.getAttribute('role') === 'menuitem') {
          results.push(node);
        }
      } else if (
        selector.startsWith('[data-testid="conversation-row-sidebar"]')
        && selector.includes('[data-cascade-id="')
      ) {
        const expectedId = selector.match(/\[data-cascade-id="([^"]+)"\]/)?.[1];
        if (
          node.getAttribute('data-testid') === 'conversation-row-sidebar'
          && node.getAttribute('data-cascade-id') === expectedId
        ) {
          results.push(node);
        }
      } else if (selectors.includes(node.tagName) || selector === 'button') {
        if (selector === 'button' && node.tagName !== 'BUTTON') {
          // skip
        } else {
          results.push(node);
        }
      }
      for (const child of node.children) {
        traverse(child);
      }
    };

    traverse(this.root);
    return results;
  },
  querySelector(selector) {
    const results = this.querySelectorAll(selector);
    return results.length > 0 ? results[0] : null;
  }
};

// Global variables to simulate browser environment
global.window = {
  __agBridge: null,
  innerHeight: 900,
  innerWidth: 1440,
  getComputedStyle(element) {
    return {
      display: element.getAttribute('data-display') || 'block',
      visibility: element.getAttribute('data-visibility') || 'visible',
      pointerEvents: element.getAttribute('data-pointer-events') || 'auto',
      opacity: element.getAttribute('data-opacity') || '1',
      position: element.getAttribute('data-position') || 'static',
      overflowY: element.getAttribute('data-overflow-y') || 'visible'
    };
  }
};
global.Element = MockNode;
global.HTMLElement = MockNode;
global.document = mockDocument;
global.location = { href: 'http://localhost/c/123' };
global.history = { pushState() {} };
global.Event = class {
  constructor(type, options = {}) {
    this.type = type;
    Object.assign(this, options);
  }
};
global.InputEvent = class {};
global.ClipboardEvent = class {};
global.KeyboardEvent = class {};
global.DataTransfer = class {};

// Load and evaluate bridge.js
const bridgePath = path.join(__dirname, '../src/bridge.js');
const bridgeCode = fs.readFileSync(bridgePath, 'utf8');
eval(bridgeCode);

const bridge = global.window.__agBridge;

console.log('Bridge loaded, version:', bridge._version);

// Test cases runner
async function runTests() {
  let passed = true;

  const assert = (condition, message) => {
    if (!condition) {
      console.error('❌ FAIL:', message);
      passed = false;
    } else {
      console.log('✅ PASS:', message);
    }
  };

  // --- Test Case 1: Empty SVG Tags ---
  console.log('\n--- Test 1: Empty SVG Tags ---');
  mockDocument.root = new MockNode('BODY');
  const projectDiv = new MockNode('div', 'Project EmptySVG');
  const btn = new MockNode('button');
  const emptySvg = new MockNode('svg'); // Empty SVG tag
  btn.appendChild(emptySvg);
  projectDiv.appendChild(btn);
  mockDocument.root.appendChild(projectDiv);

  // Calling should not throw error, should just return false (since no valid plus button path exists)
  try {
    const result = bridge.startNewConversationForProject('Project EmptySVG');
    assert(result instanceof Promise, 'startNewConversationForProject should return a Promise');
    const value = await result;
    assert(value === false, 'Should return false when no semantic project button exists');
  } catch (e) {
    assert(false, 'Threw exception: ' + e.message);
  }

  // --- Test Case 2: Missing/Falsy Project Name ---
  console.log('\n--- Test 2: Missing/Falsy Project Name ---');

  // A. null
  try {
    const value = await bridge.startNewConversationForProject(null);
    assert(value === false, 'Falsy project name (null) should return false');
  } catch (e) {
    console.error('Crash on null project name:', e);
    assert(false, 'Crashed on null project name');
  }

  // B. undefined
  try {
    const value = await bridge.startNewConversationForProject(undefined);
    assert(value === false, 'Falsy project name (undefined) should return false');
  } catch (e) {
    console.error('Crash on undefined project name:', e);
    assert(false, 'Crashed on undefined project name');
  }

  // C. empty string ""
  // Let's create an empty div and a plus button
  mockDocument.root = new MockNode('BODY');
  const container = new MockNode('div');
  const realPlusBtn = new MockNode('button');
  const svg = new MockNode('svg');
  const path = new MockNode('path', '', { d: 'M450-450H220' });
  svg.appendChild(path);
  realPlusBtn.appendChild(svg);
  container.appendChild(realPlusBtn);
  mockDocument.root.appendChild(container);

  try {
    const value = await bridge.startNewConversationForProject('');
    console.log('Result for empty string:', value, 'Plus button clicked:', realPlusBtn.clicked);
    assert(realPlusBtn.clicked === false, 'Plus button should NOT be clicked for empty project name');
  } catch (e) {
    assert(false, 'Crashed on empty string project name: ' + e.message);
  }

  // --- Test Case 3: Current global conversation anchor ---
  console.log('\n--- Test 3: Current Global Conversation Anchor ---');
  mockDocument.root = new MockNode('BODY');
  const staleConversationLink = new MockNode('a', 'New Conversation', {
    'data-testid': 'new-conversation-button',
    'data-display': 'none'
  });
  const projectConversationLink = new MockNode('a', 'New Conversation', {
    'aria-label': 'New Conversation in Project'
  });
  const globalConversationLink = new MockNode('a', '', {
    'data-testid': 'new-conversation-button'
  });
  globalConversationLink.appendChild(new MockNode('span', 'New Conversation'));
  mockDocument.root.appendChild(staleConversationLink);
  mockDocument.root.appendChild(projectConversationLink);
  mockDocument.root.appendChild(globalConversationLink);

  const globalConversationStarted = await bridge.startNewConversation();
  assert(
    globalConversationStarted === true,
    'Should resolve the current global New Conversation anchor'
  );
  assert(
    globalConversationLink.clicked === true,
    'Should click the current global New Conversation anchor'
  );
  assert(
    staleConversationLink.clicked === false,
    'Should ignore a hidden stale New Conversation anchor'
  );
  assert(
    projectConversationLink.clicked === false,
    'Should ignore a project-specific New Conversation anchor'
  );

  // --- Test Case 3b: Active chat archive action outside virtualized sidebar ---
  console.log('\n--- Test 3b: Active Chat Titlebar Archive ---');
  const archiveChatId = '11111111-1111-4111-8111-111111111111';
  global.location.href = `http://localhost/c/${archiveChatId}`;
  mockDocument.root = new MockNode('BODY');
  const titlebarMenu = new MockNode('button', '', {
    'data-testid': 'titlebar-more-actions',
    'aria-label': 'More actions'
  });
  const hiddenArchiveItem = new MockNode('div', 'Archive', {
    role: 'menuitem',
    'data-display': 'none'
  });
  const foreignArchiveItem = new MockNode('div', 'Archive', {
    role: 'menuitem'
  });
  const visibleArchiveItem = new MockNode('div', 'Archive', {
    role: 'menuitem'
  });
  titlebarMenu.onClick = () => {
    mockDocument.root.appendChild(visibleArchiveItem);
  };
  mockDocument.root.appendChild(titlebarMenu);
  mockDocument.root.appendChild(hiddenArchiveItem);
  mockDocument.root.appendChild(foreignArchiveItem);

  const archiveResult = await bridge.archiveChat(archiveChatId);
  assert(
    archiveResult.success === true,
    'Should archive the active chat without a rendered sidebar pill'
  );
  assert(titlebarMenu.clicked === true, 'Should open the active chat titlebar menu');
  assert(visibleArchiveItem.clicked === true, 'Should click the visible exact Archive menu item');
  assert(hiddenArchiveItem.clicked === false, 'Should ignore hidden stale Archive menu items');
  assert(foreignArchiveItem.clicked === false, 'Should ignore Archive items from another open menu');

  // --- Test Case 3c: Active archived chat restore via titlebar menu ---
  console.log('\n--- Test 3c: Active Chat Titlebar Restore ---');
  const restoreChatId = '22222222-2222-4222-8222-222222222222';
  global.location.href = `http://localhost/c/${restoreChatId}`;
  mockDocument.root = new MockNode('BODY');
  const restoreTitlebarMenu = new MockNode('button', '', {
    'data-testid': 'titlebar-more-actions',
    'aria-label': 'More actions'
  });
  const visibleRestoreItem = new MockNode('div', 'Restore', {
    role: 'menuitem'
  });
  const foreignRestoreItem = new MockNode('div', 'Restore', {
    role: 'menuitem'
  });
  restoreTitlebarMenu.onClick = () => {
    mockDocument.root.appendChild(visibleRestoreItem);
  };
  mockDocument.root.appendChild(restoreTitlebarMenu);
  mockDocument.root.appendChild(foreignRestoreItem);

  const restoreResult = await bridge.restoreChat(restoreChatId);
  assert(
    restoreResult.success === true,
    'Should restore the active archived chat through its titlebar menu'
  );
  assert(restoreTitlebarMenu.clicked === true, 'Should open the restore titlebar menu');
  assert(visibleRestoreItem.clicked === true, 'Should click the exact Restore menu item');
  assert(foreignRestoreItem.clicked === false, 'Should ignore Restore items from another open menu');

  // --- Test Case 3d: Anti-Gravity 2.11 sidebar row fallback ---
  console.log('\n--- Test 3d: Current Sidebar Archive Row ---');
  const sidebarChatId = '33333333-3333-4333-8333-333333333333';
  global.location.href = 'http://localhost/c/44444444-4444-4444-8444-444444444444';
  mockDocument.root = new MockNode('BODY');
  const sidebarRow = new MockNode('div', '', {
    'data-testid': 'conversation-row-sidebar',
    'data-cascade-id': sidebarChatId
  });
  const sidebarArchiveButton = new MockNode('button', '', {
    'data-testid': 'conversation-archive-button',
    'aria-label': 'Archive conversation'
  });
  sidebarRow.appendChild(sidebarArchiveButton);
  mockDocument.root.appendChild(sidebarRow);

  const sidebarArchiveResult = await bridge.archiveChat(sidebarChatId);
  assert(
    sidebarArchiveResult.success === true,
    'Should archive an Anti-Gravity 2.11 sidebar row without a legacy pill'
  );
  assert(sidebarArchiveButton.clicked === true, 'Should click the 2.11 archive button');
  global.location.href = 'http://localhost/c/123';

  // --- Test Case 4: Nested Elements and Includes Fallback ---
  console.log('\n--- Test 4: Nested Elements & Includes Fallback ---');
  // Setup sidebar with two projects inside a wrapper
  mockDocument.root = new MockNode('BODY');
  const listWrapper = new MockNode('div'); // Wrapper containing all projects

  const proj1 = new MockNode('div', '', { role: 'button' });
  const proj1Span = new MockNode('span', 'Project Alpha');
  const btn1Wrapper = new MockNode('div');
  const btn1 = new MockNode('button', '', { 'aria-label': 'New Conversation in Project' });
  btn1Wrapper.appendChild(btn1);
  proj1.appendChild(proj1Span);
  proj1.appendChild(btn1Wrapper);

  const proj2 = new MockNode('div', '', { role: 'button' });
  const proj2Span = new MockNode('span', 'D:\\Projects\\Project Beta');
  const btn2Wrapper = new MockNode('div');
  const btn2 = new MockNode('button', '', { 'aria-label': 'New Conversation in Project' });
  btn2Wrapper.appendChild(btn2);
  proj2.appendChild(proj2Span);
  proj2.appendChild(btn2Wrapper);

  listWrapper.appendChild(proj1);
  listWrapper.appendChild(proj2);
  mockDocument.root.appendChild(listWrapper);

  // If we search for 'Project Beta' with includes fallback, does it match the listWrapper parent,
  // and click Project Alpha's button instead?
  // Let's force fallback by searching for 'Beta' (substring).
  const value = await bridge.startNewConversationForProject('Project Beta');
  assert(value === true, 'Should resolve a unique project basename');
  assert(btn2.clicked === true, 'Should click Project Beta plus button');
  assert(btn1.clicked === false, 'Should NOT click Project Alpha plus button instead of Beta');

  const legacyProjects = bridge.getProjectList();
  assert(legacyProjects.count === 2, 'Should list projects from legacy button rows');
  assert(
    legacyProjects.projects[1].display_name === 'D:\\Projects\\Project Beta',
    'Should preserve the legacy project row label'
  );

  // --- Test Case 5: Current project card header with adjacent anchor ---
  console.log('\n--- Test 5: Current Project Card DOM ---');
  mockDocument.root = new MockNode('BODY');

  const createCurrentProject = name => {
    const project = new MockNode('div');
    const header = new MockNode('button', name, { 'data-project-card': 'true' });
    const actions = new MockNode('div');
    const link = new MockNode('a', '', {
      'aria-label': 'New Conversation in Project',
      href: '/?section=' + name
    });
    actions.appendChild(link);
    project.appendChild(header);
    project.appendChild(actions);
    return { project, link };
  };

  const gamma = createCurrentProject('Project Gamma');
  const delta = createCurrentProject('Project Delta');
  mockDocument.root.appendChild(gamma.project);
  mockDocument.root.appendChild(delta.project);

  const currentProjects = bridge.getProjectList();
  assert(currentProjects.count === 2, 'Should list projects from current project cards');
  assert(
    currentProjects.projects.map(project => project.display_name).join('|')
      === 'Project Gamma|Project Delta',
    'Should read current project names from data-project-card headers'
  );

  const currentValue = await bridge.startNewConversationForProject('Project Delta');
  assert(currentValue === true, 'Should resolve a current project card');
  assert(delta.link.clicked === true, 'Should click the current project anchor');
  assert(gamma.link.clicked === false, 'Should not click a neighboring project anchor');

  // --- Test Case 5b: Cold-start collapsed project conversation discovery ---
  console.log('\n--- Test 5b: Cold-start Collapsed Project Discovery ---');
  mockDocument.root = new MockNode('BODY');
  const collapsedProject = new MockNode('button', 'Antigravity Agent', {
    'data-project-card': 'true',
    'aria-expanded': 'false'
  });
  const collapsedChatId = '55555555-5555-4555-8555-555555555555';
  const secondCollapsedProject = new MockNode('button', 'sample-api', {
    'data-project-card': 'true',
    'aria-expanded': 'false'
  });
  const secondCollapsedChatId = '88888888-8888-4888-8888-888888888888';
  const renderProjectChat = (project, chatId, title) => {
    project.attrs['aria-expanded'] = 'true';
    setTimeout(() => {
      const row = new MockNode('div', '', {
        role: 'button',
        'data-testid': 'conversation-row-sidebar',
        'data-cascade-id': chatId
      });
      row.className = 'ml-[22px]';
      row.appendChild(new MockNode('span', title, {
        'data-testid': `convo-pill-${chatId}`
      }));
      mockDocument.root.appendChild(row);
    }, 0);
  };
  collapsedProject.onClick = () => renderProjectChat(
    collapsedProject,
    collapsedChatId,
    'Generated chat title'
  );
  secondCollapsedProject.onClick = () => renderProjectChat(
    secondCollapsedProject,
    secondCollapsedChatId,
    'Second generated chat title'
  );
  mockDocument.root.appendChild(collapsedProject);
  mockDocument.root.appendChild(secondCollapsedProject);

  const coldStartChats = await bridge.getChatList();
  assert(collapsedProject.clicked === true, 'Should expand a collapsed project before discovery');
  assert(secondCollapsedProject.clicked === true, 'Should expand every collapsed project');
  assert(coldStartChats.count === 2, 'Should discover project chats rendered after expansion');
  assert(
    coldStartChats.chats[0]?.title === 'Generated chat title',
    'Should return the genuine visible project chat title'
  );
  assert(coldStartChats.chats[0]?.project_chat === true, 'Should mark the chat as a project chat');

  // --- Test Case 5bb: Projects materialized after earlier expansion ---
  console.log('\n--- Test 5bb: Iterative Project Expansion ---');
  mockDocument.root = new MockNode('BODY');
  const iterativeFirstId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const iterativeSecondId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const iterativeFirstProject = new MockNode('button', 'First virtual project', {
    'data-project-card': 'true',
    'aria-expanded': 'false'
  });
  const iterativeSecondProject = new MockNode('button', 'Second virtual project', {
    'data-project-card': 'true',
    'aria-expanded': 'false'
  });
  const appendIterativeChat = (project, chatId, title) => {
    project.attrs['aria-expanded'] = 'true';
    const row = new MockNode('div', '', {
      role: 'button',
      'data-testid': 'conversation-row-sidebar',
      'data-cascade-id': chatId
    });
    row.className = 'ml-[22px]';
    row.appendChild(new MockNode('span', title, {
      'data-testid': `convo-pill-${chatId}`
    }));
    mockDocument.root.appendChild(row);
  };
  iterativeSecondProject.onClick = () => appendIterativeChat(
    iterativeSecondProject,
    iterativeSecondId,
    'Second virtual chat'
  );
  iterativeFirstProject.onClick = () => {
    appendIterativeChat(iterativeFirstProject, iterativeFirstId, 'First virtual chat');
    mockDocument.root.appendChild(iterativeSecondProject);
  };
  mockDocument.root.appendChild(iterativeFirstProject);

  const iterativeChats = await bridge.getChatList();
  assert(iterativeFirstProject.clicked === true, 'Should expand the first materialized project');
  assert(
    iterativeSecondProject.clicked === true,
    'Should rescan and expand a project materialized after the first expansion'
  );
  assert(iterativeChats.count === 2, 'Should discover chats from every iteratively materialized project');
  assert(
    iterativeChats.complete === false,
    'Should not claim virtualized completeness without the canonical sidebar wrapper'
  );

  // --- Test Case 5bc: Chats and projects across virtualized scroll viewports ---
  console.log('\n--- Test 5bc: Virtualized Sidebar Sweep ---');
  mockDocument.root = new MockNode('BODY');
  const virtualScroller = new MockNode('div', '', {
    'data-testid': 'conversation-list-sidebar',
    clientHeight: 200,
    scrollHeight: 400,
    'data-overflow-y': 'auto'
  });
  const virtualFirstId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  const virtualSecondId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  const virtualFirstProject = new MockNode('button', 'Top virtual project', {
    'data-project-card': 'true',
    'aria-expanded': 'false'
  });
  const virtualSecondProject = new MockNode('button', 'Bottom virtual project', {
    'data-project-card': 'true',
    'aria-expanded': 'false'
  });
  const virtualRow = (chatId, title) => {
    const row = new MockNode('div', '', {
      role: 'button',
      'data-testid': 'conversation-row-sidebar',
      'data-cascade-id': chatId
    });
    row.className = 'ml-[22px]';
    row.appendChild(new MockNode('span', title, {
      'data-testid': `convo-pill-${chatId}`
    }));
    return row;
  };
  const renderVirtualViewport = atBottom => {
    const project = atBottom ? virtualSecondProject : virtualFirstProject;
    const chatId = atBottom ? virtualSecondId : virtualFirstId;
    const title = atBottom ? 'Bottom virtual chat' : 'Top virtual chat';
    for (const child of virtualScroller.children) child.parentElement = null;
    virtualScroller.children = [];
    virtualScroller.appendChild(project);
    if (project.getAttribute('aria-expanded') === 'true') {
      virtualScroller.appendChild(virtualRow(chatId, title));
    }
  };
  virtualFirstProject.onClick = () => {
    virtualFirstProject.attrs['aria-expanded'] = 'true';
    renderVirtualViewport(false);
  };
  virtualSecondProject.onClick = () => {
    virtualSecondProject.attrs['aria-expanded'] = 'true';
    renderVirtualViewport(true);
  };
  const visitedVirtualOffsets = [];
  virtualScroller.onScroll = top => {
    visitedVirtualOffsets.push(top);
    setTimeout(() => renderVirtualViewport(top >= virtualScroller.clientHeight), 0);
  };
  renderVirtualViewport(false);
  mockDocument.root.appendChild(virtualScroller);

  const virtualChats = await bridge.getChatList();
  assert(virtualFirstProject.clicked === true, 'Should expand a project in the top viewport');
  assert(virtualSecondProject.clicked === true, 'Should scroll and expand a project in the bottom viewport');
  assert(
    visitedVirtualOffsets.some(offset => offset >= virtualScroller.clientHeight),
    'Should visit the second canonical sidebar viewport'
  );
  assert(
    virtualChats.count === 2,
    'Should retain chats collected from virtualized viewports after their rows unmount'
  );
  assert(
    virtualChats.chats.map(chat => chat.id).sort().join('|')
      === [virtualFirstId, virtualSecondId].sort().join('|'),
    'Should retain the exact chat IDs from both virtualized viewports'
  );
  assert(
    virtualChats.chats.map(chat => chat.title).sort().join('|')
      === ['Bottom virtual chat', 'Top virtual chat'].sort().join('|'),
    'Should retain genuine chat titles after earlier rows unmount'
  );
  assert(
    virtualChats.chats.every(chat => chat.project_chat === true),
    'Should preserve project-chat classification across the sidebar sweep'
  );
  assert(virtualScroller.scrollTop === 0, 'Should restore the user\'s original sidebar position');

  // --- Test Case 5bd: A stale project button must not receive a click storm ---
  console.log('\n--- Test 5bd: Unresponsive Project Button ---');
  mockDocument.root = new MockNode('BODY');
  let unresponsiveClickCount = 0;
  const unresponsiveProject = new MockNode('button', 'Unresponsive project', {
    'data-project-card': 'true',
    'aria-expanded': 'false'
  });
  unresponsiveProject.onClick = () => {
    unresponsiveClickCount += 1;
  };
  mockDocument.root.appendChild(unresponsiveProject);

  const incompleteChats = await bridge.getChatList();
  assert(unresponsiveClickCount === 1, 'Should click an unresponsive project only once per scan');
  assert(incompleteChats.complete === false, 'Should not claim a complete scan while a project stays closed');
  assert(incompleteChats.limit_reached === true, 'Should expose the incomplete materialization state');

  // --- Test Case 5be: React remounts must not bypass the click guard ---
  console.log('\n--- Test 5be: Remounted Unresponsive Project ---');
  mockDocument.root = new MockNode('BODY');
  let remountedClickCount = 0;
  const mountUnresponsiveProject = () => {
    const project = new MockNode('button', 'Remounted unresponsive project', {
      'data-project-card': 'true',
      'aria-expanded': 'false'
    });
    project.onClick = () => {
      remountedClickCount += 1;
      project.parentElement = null;
      mockDocument.root.children = [];
      mountUnresponsiveProject();
    };
    mockDocument.root.appendChild(project);
  };
  mountUnresponsiveProject();

  const remountedIncompleteChats = await bridge.getChatList();
  assert(
    remountedClickCount <= 2,
    'Should bound retries when an unresponsive project is remounted'
  );
  assert(
    remountedIncompleteChats.complete === false,
    'Should keep a remounted closed project scan incomplete'
  );

  // --- Test Case 5c: Empty visible title stays empty ---
  console.log('\n--- Test 5c: Empty Visible Chat Title ---');
  mockDocument.root = new MockNode('BODY');
  const untitledChatId = '66666666-6666-4666-8666-666666666666';
  const untitledRow = new MockNode('div', '', { role: 'button' });
  untitledRow.appendChild(new MockNode('span', '', {
    'data-testid': `convo-pill-${untitledChatId}`
  }));
  mockDocument.root.appendChild(untitledRow);

  const untitledChats = await bridge.getChatList();
  assert(untitledChats.count === 1, 'Should enumerate a visible untitled chat');
  assert(
    untitledChats.chats[0]?.title === '',
    'Should return an empty title instead of synthesizing a technical Chat ID title'
  );

  // --- Test Case 5d: Current 2.11 row without a separately rendered pill ---
  console.log('\n--- Test 5d: Current Sidebar Row Discovery ---');
  mockDocument.root = new MockNode('BODY');
  const rowOnlyChatId = '77777777-7777-4777-8777-777777777777';
  const rowOnlyChat = new MockNode('div', 'Row-only generated title', {
    role: 'button',
    'data-testid': 'conversation-row-sidebar',
    'data-cascade-id': rowOnlyChatId
  });
  mockDocument.root.appendChild(rowOnlyChat);

  const rowOnlyChats = await bridge.getChatList();
  assert(rowOnlyChats.count === 1, 'Should enumerate a current 2.11 sidebar row');
  assert(
    rowOnlyChats.chats[0]?.title === 'Row-only generated title',
    'Should return the genuine visible row title when no pill exists'
  );

  // --- Test Case 5e: Separately virtualized pill enriches its sidebar row ---
  console.log('\n--- Test 5e: Separate Sidebar Pill Merge ---');
  mockDocument.root = new MockNode('BODY');
  const mergedChatId = '99999999-9999-4999-8999-999999999999';
  const mergedRow = new MockNode('div', '', {
    role: 'button',
    'data-testid': 'conversation-row-sidebar',
    'data-cascade-id': mergedChatId
  });
  const separatelyRenderedPill = new MockNode('span', 'Virtualized generated title', {
    'data-testid': `convo-pill-${mergedChatId}`
  });
  mockDocument.root.appendChild(mergedRow);
  mockDocument.root.appendChild(separatelyRenderedPill);

  const mergedChats = await bridge.getChatList();
  assert(mergedChats.count === 1, 'Should deduplicate a row and separate pill by chat ID');
  assert(
    mergedChats.chats[0]?.title === 'Virtualized generated title',
    'Should enrich an empty sidebar row with its separately rendered pill title'
  );

  // --- Test Case 5f: A genuine pill title outranks later row-only text ---
  console.log('\n--- Test 5f: Sidebar Title Source Priority ---');
  mockDocument.root = new MockNode('BODY');
  const priorityChatId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
  const priorityRow = new MockNode('div', '', {
    role: 'button',
    'data-testid': 'conversation-row-sidebar',
    'data-cascade-id': priorityChatId
  });
  priorityRow.appendChild(new MockNode('span', 'Genuine generated title', {
    'data-testid': `convo-pill-${priorityChatId}`
  }));
  mockDocument.root.appendChild(priorityRow);
  const priorityChats = new Map();
  bridge._collectVisibleSidebarChats(priorityChats, null);

  mockDocument.root = new MockNode('BODY');
  const transientPriorityRow = new MockNode('div', 'Genuine generated title6d', {
    role: 'button',
    'data-testid': 'conversation-row-sidebar',
    'data-cascade-id': priorityChatId
  });
  mockDocument.root.appendChild(transientPriorityRow);
  bridge._collectVisibleSidebarChats(priorityChats, null);
  assert(
    priorityChats.get(priorityChatId)?.title === 'Genuine generated title',
    'Should not replace a pill title with later row-only metadata'
  );

  // --- Test Case 5g: Modern scans ignore legacy IDs outside the sidebar ---
  console.log('\n--- Test 5g: Scoped Legacy Fallback ---');
  mockDocument.root = new MockNode('BODY');
  const emptyModernSidebar = new MockNode('div', '', {
    'data-testid': 'conversation-list-sidebar',
    clientHeight: 200,
    scrollHeight: 200
  });
  mockDocument.root.appendChild(emptyModernSidebar);
  mockDocument.root.appendChild(new MockNode('div', 'Unrelated page state', {
    'data-chat-id': 'ffffffff-ffff-4fff-8fff-ffffffffffff'
  }));
  const scopedLegacyChats = await bridge.getChatList();
  assert(
    scopedLegacyChats.count === 0,
    'Should not import legacy chat IDs outside a modern sidebar'
  );

  // --- Test Case 6: Virtualized worker with separately rendered columns ---
  console.log('\n--- Test 6: Ordered Virtualized Project Controls ---');
  mockDocument.root = new MockNode('BODY');
  const headers = new MockNode('div');
  headers.appendChild(new MockNode('button', 'Project Epsilon', {
    'data-project-card': 'true'
  }));
  headers.appendChild(new MockNode('button', 'Project Zeta', {
    'data-project-card': 'true'
  }));
  const controls = new MockNode('div');
  const epsilonLink = new MockNode('a', '', {
    'aria-label': 'New Conversation in Project'
  });
  const zetaLink = new MockNode('a', '', {
    'aria-label': 'New Conversation in Project'
  });
  controls.appendChild(epsilonLink);
  controls.appendChild(zetaLink);
  mockDocument.root.appendChild(headers);
  mockDocument.root.appendChild(controls);

  const virtualProjects = bridge.getProjectList();
  assert(virtualProjects.count === 2, 'Should pair equally ordered virtualized headers and controls');
  assert(
    virtualProjects.projects[1].display_name === 'Project Zeta',
    'Should retain the ordered virtualized project name'
  );
  const virtualValue = await bridge.startNewConversationForProject('Project Zeta');
  assert(virtualValue === true, 'Should resolve an ordered virtualized project');
  assert(zetaLink.clicked === true, 'Should click the matching ordered virtualized control');
  assert(epsilonLink.clicked === false, 'Should not click a neighboring virtualized control');

  if (!passed) process.exitCode = 1;
}

runTests().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
