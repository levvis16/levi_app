const API_BASE = "";
let token = null;
let pendingAttachments = [];
let currentUser = null;
let currentDialogId = null;
let ws = null;
let currentGroupId = null;
let groupsList = [];
let isUploading = false;
let pingInterval = null;

const authPage = document.getElementById('authPage');
const chatPage = document.getElementById('chatPage');
const currentUserNameSpan = document.getElementById('currentUserName');
const dialogsList = document.getElementById('dialogsList');
const messagesContainer = document.getElementById('messagesContainer');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendMessageBtn');

// Tabs
document.querySelectorAll('.auth-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const tabName = tab.dataset.tab;
        document.getElementById('loginForm').classList.toggle('active', tabName === 'login');
        document.getElementById('registerForm').classList.toggle('active', tabName === 'register');
    });
});

// Register
document.getElementById('doRegisterBtn').onclick = async () => {
    const name = document.getElementById('regName').value;
    const age = document.getElementById('regAge').value;
    const password = document.getElementById('regPassword').value;
    if (!name || !age || !password) return alert('Заполните все поля');
    const res = await fetch(`${API_BASE}/users/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, age: parseInt(age), password })
    });
    if (res.ok) {
        alert('Регистрация успешна! Теперь войдите');
        document.querySelector('.auth-tab[data-tab="login"]').click();
    } else {
        alert('Ошибка регистрации');
    }
};

// Login
document.getElementById('doLoginBtn').onclick = async () => {
    const name = document.getElementById('loginName').value;
    const password = document.getElementById('loginPassword').value;
    if (!name || !password) return alert('Введите имя и пароль');
    const formData = new URLSearchParams();
    formData.append('username', name);
    formData.append('password', password);
    const res = await fetch(`${API_BASE}/users/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData
    });
    if (res.ok) {
        const data = await res.json();
        token = data.access_token;
        currentUser = name;
        localStorage.setItem('token', token);
        localStorage.setItem('user', currentUser);
        showChatPage();
    } else {
        alert('Неверные имя или пароль');
    }
};

document.getElementById('attachBtn').onclick = () => {
    document.getElementById('fileInput').click();
};

document.getElementById('fileInput').onchange = async (e) => {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;
    
    isUploading = true;
    sendBtn.disabled = true;
    messageInput.disabled = true;
    
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/upload/`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });
        if (res.ok) {
            const data = await res.json();
            pendingAttachments.push(data);
            addPreviewItem(data);
        } else {
            alert('Ошибка загрузки файла');
        }
    }
    
    isUploading = false;
    sendBtn.disabled = false;
    messageInput.disabled = false;
    e.target.value = '';
};

// Logout
document.getElementById('logoutBtn').onclick = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    clearInterval(pingInterval);  // останавливаем ping
    token = null;                  // обнуляем до закрытия, иначе onclose переподключит
    if (ws) ws.close();
    currentGroupId = null;
    currentUser = null;
    currentDialogId = null;
    authPage.classList.remove('hidden');
    chatPage.classList.add('hidden');
};

function addPreviewItem(fileData) {
    const preview = document.getElementById('previewArea');
    const div = document.createElement('div');
    div.className = 'preview-item';
    div.dataset.url = fileData.url;
    
    if (fileData.type.startsWith('image/')) {
        div.innerHTML = `<img src="${fileData.url}" style="width:40px;height:40px;border-radius:8px">`;
    } else {
        div.innerHTML = `<span>📄 ${fileData.name.substring(0, 15)}</span>`;
    }
    div.innerHTML += `<button class="preview-remove" data-url="${fileData.url}">✕</button>`;
    preview.appendChild(div);
    
    div.querySelector('.preview-remove').onclick = () => {
        pendingAttachments = pendingAttachments.filter(a => a.url !== fileData.url);
        div.remove();
    };
}


function showChatPage() {
    authPage.classList.add('hidden');
    chatPage.classList.remove('hidden');
    currentUserNameSpan.textContent = currentUser;
    connectWebSocket();
    loadDialogs();
}

// WebSocket
function connectWebSocket() {
    if (!token) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/dialogs/ws/${token}`);

    ws.onopen = () => {
        console.log("WebSocket connected");
        // Пингуем каждые 20 сек чтобы Render не закрыл соединение
        pingInterval = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "ping" }));
            }
        }, 20000);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            console.log("WS received:", data);

            if (data.type === 'new_group_message') {
                if (currentGroupId === data.group_id) {
                    addMessageToChat(data.message);
                }
                loadDialogs();
            }

            if (data.type === 'new_message') {
                if (currentDialogId === data.dialog_id) {
                    addMessageToChat(data.message);
                }
                loadDialogs();
            }

            if (data.type === 'messages_read') {
                // на будущее: обновить галочки прочитанных
            }

        } catch(e) {
            console.warn("WS parse error", e);
        }
    };

    ws.onclose = (event) => {
        console.log("WebSocket closed, code:", event.code);
        clearInterval(pingInterval);
        // Переподключаемся через 3 секунды если пользователь залогинен
        if (token) {
            setTimeout(() => connectWebSocket(), 3000);
        }
    };

    ws.onerror = (err) => {
        console.error("WebSocket error:", err);
    };
}

// Load dialogs
async function loadDialogs() {
    if (!token) return;
    
    // Загружаем диалоги
    const dialogsRes = await fetch(`${API_BASE}/dialogs/`, {
        headers: { 'Authorization': `Bearer ${token}` }
    });
    
    // Загружаем группы
    const groupsRes = await fetch(`${API_BASE}/groups/`, {
        headers: { 'Authorization': `Bearer ${token}` }
    });
    
    if (dialogsRes.ok && groupsRes.ok) {
        const dialogs = await dialogsRes.json();
        const groups = await groupsRes.json();
        groupsList = groups;
        
        if (dialogs.length === 0 && groups.length === 0) {
            dialogsList.innerHTML = '<div class="empty-state">Нет чатов</div>';
            return;
        }
        
        let html = '';
        
        // Личные диалоги
        if (dialogs.length > 0) {
            html += `<div class="section-header">💬 Личные чаты</div>`;
            html += dialogs.map(d => `
                <div class="dialog-item ${currentDialogId === d.id && !currentGroupId ? 'active' : ''}" data-dialog-id="${d.id}" data-type="dialog">
                    <div class="dialog-avatar">${d.companion_name[0].toUpperCase()}</div>
                    <div class="dialog-info">
                        <div class="dialog-name">${escapeHtml(d.companion_name)}</div>
                        <div class="dialog-last-msg">${escapeHtml(d.last_message?.substring(0, 40) || 'Нет сообщений')}</div>
                    </div>
                    ${d.unread_count > 0 ? `<div class="unread-badge">${d.unread_count}</div>` : ''}
                    <button class="dialog-menu" data-id="${d.id}" data-type="dialog">⋯</button>
                </div>
            `).join('');
        }
        
        // Группы
        if (groups.length > 0) {
            html += `<div class="section-header">👥 Группы</div>`;
            html += groups.map(g => `
                <div class="dialog-item ${currentGroupId === g.id && !currentDialogId ? 'active' : ''}" data-group-id="${g.id}" data-type="group">
                    <div class="dialog-avatar group-avatar">👥</div>
                    <div class="dialog-info">
                        <div class="dialog-name">${escapeHtml(g.name)}</div>
                        <div class="dialog-last-msg">${escapeHtml(g.last_message?.substring(0, 40) || 'Нет сообщений')}</div>
                    </div>
                    <button class="dialog-menu" data-id="${g.id}" data-type="group">⋯</button>
                </div>
            `).join('');
        }
        
        dialogsList.innerHTML = html;
        
        // Обработчики для диалогов
        document.querySelectorAll('[data-dialog-id]').forEach(el => {
            const id = parseInt(el.dataset.dialogId);
            const name = el.querySelector('.dialog-name')?.textContent || '';
            el.addEventListener('click', (e) => {
                if (e.target.classList.contains('dialog-menu')) return;
                selectDialog(id, name);
            });
            const menuBtn = el.querySelector('.dialog-menu');
            if (menuBtn) {
                menuBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showChatMenu(menuBtn, id, 'dialog');
                });
            }
        });
        
        // Обработчики для групп
        document.querySelectorAll('[data-group-id]').forEach(el => {
            const id = parseInt(el.dataset.groupId);
            const gname = el.querySelector('.dialog-name')?.textContent || '';
            el.addEventListener('click', (e) => {
                if (e.target.classList.contains('dialog-menu')) return;
                selectGroup(id, gname);
            });
            const menuBtn = el.querySelector('.dialog-menu');
            if (menuBtn) {
                menuBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showChatMenu(menuBtn, id, 'group');
                });
            }
        });
    }
}

async function showChatMenu(btn, id, type) {
    const existingMenu = document.querySelector('.dropdown-menu');
    if (existingMenu) existingMenu.remove();
    
    const menu = document.createElement('div');
    menu.className = 'dropdown-menu';
    menu.innerHTML = `<div class="dropdown-item delete">🗑 Удалить ${type === 'dialog' ? 'диалог' : 'группу'}</div>`;
    
    const rect = btn.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.top = `${rect.bottom + 5}px`;
    menu.style.left = `${rect.right - 140}px`;
    document.body.appendChild(menu);
    
    menu.querySelector('.delete').addEventListener('click', async () => {
        const url = type === 'dialog' 
            ? `${API_BASE}/dialogs/${id}`
            : `${API_BASE}/groups/${id}`;
        const res = await fetch(url, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
            if ((type === 'dialog' && currentDialogId === id) ||
                (type === 'group' && currentGroupId === id)) {
                currentDialogId = null;
                currentGroupId = null;
                messagesContainer.innerHTML = '<div class="empty-state">Выберите чат</div>';
                messageInput.disabled = true;
                sendBtn.disabled = true;
                document.getElementById('inviteSection').style.display = 'none';
            }
            await loadDialogs();
        } else {
            alert('Ошибка удаления');
        }
        menu.remove();
    });
    
    setTimeout(() => document.addEventListener('click', function closeMenu(e) {
        if (!menu.contains(e.target)) {
            menu.remove();
            document.removeEventListener('click', closeMenu);
        }
    }), 10);
}

async function selectGroup(groupId, groupName) {
    currentGroupId = groupId;
    currentDialogId = null;
    messageInput.disabled = false;
    sendBtn.disabled = false;
    openChatMobile(groupName || '');
    
    // Показываем секцию приглашения
    const inviteSection = document.getElementById('inviteSection');
    inviteSection.style.display = 'flex';
    
    await loadGroupMessages(groupId);
    await loadDialogs();
}

async function loadGroupMessages(groupId) {
    const res = await fetch(`${API_BASE}/groups/${groupId}/messages?limit=100`, {
        headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
        const messages = await res.json();
        messagesContainer.innerHTML = '';
        if (messages.length === 0) {
            messagesContainer.innerHTML = '<div class="empty-state">Нет сообщений. Напишите что-нибудь!</div>';
            return;
        }
        messages.reverse().forEach(msg => addMessageToChat(msg));
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

function showDialogMenu(btn, dialogId) {
    const existingMenu = document.querySelector('.dropdown-menu');
    if (existingMenu) existingMenu.remove();
    const menu = document.createElement('div');
    menu.className = 'dropdown-menu';
    menu.innerHTML = `<div class="dropdown-item delete">🗑 Удалить диалог</div>`;
    const rect = btn.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.top = `${rect.bottom + 5}px`;
    menu.style.left = `${rect.right - 140}px`;
    document.body.appendChild(menu);
    
    menu.querySelector('.delete').addEventListener('click', async () => {
        if (confirm('Удалить диалог?')) {
            const res = await fetch(`${API_BASE}/dialogs/${dialogId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                if (currentDialogId === dialogId) {
                    currentDialogId = null;
                    messagesContainer.innerHTML = '<div class="empty-state">Выберите диалог, чтобы начать общение</div>';
                    messageInput.disabled = true;
                    sendBtn.disabled = true;
                }
                await loadDialogs();
            } else {
                alert('Ошибка удаления');
            }
        }
        menu.remove();
    });
    setTimeout(() => document.addEventListener('click', function closeMenu(e) {
        if (!menu.contains(e.target)) {
            menu.remove();
            document.removeEventListener('click', closeMenu);
        }
    }), 10);
}

async function selectDialog(dialogId, dialogName) {
    currentDialogId = dialogId;
    currentGroupId = null;
    messageInput.disabled = false;
    sendBtn.disabled = false;
    document.getElementById('inviteSection').style.display = 'none';
    openChatMobile(dialogName || '');
    await loadMessages(dialogId);
    await fetch(`${API_BASE}/dialogs/${dialogId}/read`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
    });
    await loadDialogs();
}

async function loadMessages(dialogId) {
    const res = await fetch(`${API_BASE}/dialogs/${dialogId}/messages?limit=100`, {
        headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
        const messages = await res.json();
        messagesContainer.innerHTML = '';
        if (messages.length === 0) {
            messagesContainer.innerHTML = '<div class="empty-state">Нет сообщений. Напишите что-нибудь!</div>';
            return;
        }
        messages.reverse().forEach(msg => addMessageToChat(msg));
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

// Reply state
let replyTo = null; // { sender_name, text }

function setReply(senderName, text) {
    replyTo = { sender_name: senderName, text: text };
    const previewName = document.getElementById('replyPreviewName');
    const previewText = document.getElementById('replyPreviewText');
    if (previewName) previewName.textContent = `Ответ для ${senderName}`;
    if (previewText) previewText.textContent = text.length > 60 ? text.substring(0, 60) + '…' : text;
    
    // Принудительно задаём цвета (на случай если CSS не сработал)
    if (previewName) previewName.style.color = '#4cd964';
    if (previewText) previewText.style.color = '#c0c0c5';
    
    document.getElementById('replyPreview').style.display = 'flex';
    messageInput.focus();
}

function clearReply() {
    replyTo = null;
    document.getElementById('replyPreview').style.display = 'none';
    document.getElementById('replyPreviewName').textContent = '';
    document.getElementById('replyPreviewText').textContent = '';
}

document.getElementById('replyCancelBtn').onclick = clearReply;

function addMessageToChat(msg) {
    const isOwn = msg.sender_name === currentUser;
    const div = document.createElement('div');
    div.className = `message ${isOwn ? 'own' : 'other'}`;
    
    div.dataset.senderName = msg.sender_name || (isOwn ? currentUser : 'Собеседник');
    div.dataset.messageText = msg.text || '';
    div.dataset.messageId = msg.id;

    let attachmentsHtml = '';
    if (msg.attachments && msg.attachments.length > 0) {
        attachmentsHtml = '<div class="attachments">';
        for (const att of msg.attachments) {
            if (att.type && att.type.startsWith('image/')) {
                attachmentsHtml += `<img src="${att.url}" class="attachment-image" onclick="window.open('${att.url}')">`;
            } else if (att.type && att.type.startsWith('video/')) {
                attachmentsHtml += `<video src="${att.url}" controls class="attachment-video"></video>`;
            } else {
                attachmentsHtml += `<a href="${att.url}" class="attachment-file" download>📎 ${escapeHtml(att.name || 'Файл')}</a>`;
            }
        }
        attachmentsHtml += '</div>';
    }

    let replyHtml = '';
    if (msg.reply_to) {
        replyHtml = `
            <div class="reply-in-message">
                <div class="reply-in-message-name">↩ ${escapeHtml(msg.reply_to.sender_name)}</div>
                <div class="reply-in-message-text">${escapeHtml(msg.reply_to.text.substring(0, 80))}${msg.reply_to.text.length > 80 ? '…' : ''}</div>
            </div>`;
    }

    div.innerHTML = `
        <div class="message-name">${escapeHtml(msg.sender_name || (isOwn ? currentUser : 'Собеседник'))}</div>
        ${replyHtml}
        ${attachmentsHtml}
        ${ (msg.text && msg.text.trim() !== '')
            ? `<div class="message-bubble">${escapeHtml(msg.text)}</div>`
            : '' }
        <div class="message-time">${new Date(msg.created_at + 'Z').toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</div>
    `;

    div.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        const senderName = div.dataset.senderName;
        const messageText = div.dataset.messageText;
        if (messageText && messageText.trim()) {
            setReply(senderName, messageText);
            div.style.backgroundColor = 'rgba(52, 199, 89, 0.15)';
            setTimeout(() => div.style.backgroundColor = '', 200);
        } else {
            // Можно показать уведомление, что нельзя ответить на сообщение без текста
            const notification = document.createElement('div');
            notification.textContent = '📎 Нельзя ответить на сообщение с вложением без текста';
            notification.style.cssText = 'position:fixed; bottom:80px; left:50%; transform:translateX(-50%); background:#2c2c2e; color:white; padding:8px 16px; border-radius:20px; font-size:12px; z-index:9999;';
            document.body.appendChild(notification);
            setTimeout(() => notification.remove(), 2000);
        }
        return false;
    });

    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

document.getElementById('createGroupBtn').onclick = async () => {
    const name = document.getElementById('groupName').value;
    if (!name) return alert('Введите название группы');
    
    const res = await fetch(`${API_BASE}/groups/`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    if (res.ok) {
        document.getElementById('groupName').value = '';
        await loadDialogs();
        alert('Группа создана');
    } else {
        alert('Ошибка создания группы');
    }
};

document.getElementById('inviteUserBtn').onclick = async () => {
    if (!currentGroupId) return alert('Выберите группу');
    const userName = document.getElementById('inviteUserName').value;
    if (!userName) return alert('Введите имя пользователя');
    
    // Получаем всех пользователей
    const usersRes = await fetch(`${API_BASE}/users/`);
    if (!usersRes.ok) return alert('Ошибка загрузки пользователей');
    const users = await usersRes.json();
    const user = users.find(u => u.name === userName);
    if (!user) return alert('Пользователь не найден');
    
    const res = await fetch(`${API_BASE}/groups/${currentGroupId}/users/${user.id}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
        alert(`Пользователь ${userName} добавлен в группу`);
        document.getElementById('inviteUserName').value = '';
    } else {
        alert('Ошибка приглашения');
    }
};

document.getElementById('createDialogBtn').onclick = async () => {
    const name = document.getElementById('companionName').value;
    if (!name) return alert('Введите имя собеседника');
    const usersRes = await fetch(`${API_BASE}/users/`);
    if (usersRes.ok) {
        const users = await usersRes.json();
        const companion = users.find(u => u.name === name);
        if (!companion) return alert('Пользователь не найден');
        const res = await fetch(`${API_BASE}/dialogs/`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id_2: companion.id })
        });
        if (res.ok) {
            document.getElementById('companionName').value = '';
            await loadDialogs();
        } else {
            alert('Ошибка создания диалога');
        }
    }
};

sendBtn.onclick = async () => {
    if (isUploading) {
        alert('Подождите, файлы ещё загружаются...');
        return;
    }
    
    let text = messageInput.value.trim();

    if (!text && pendingAttachments.length === 0) return;
    
    let url;
    if (currentDialogId) {
        url = `${API_BASE}/dialogs/${currentDialogId}/messages`;
    } else if (currentGroupId) {
        url = `${API_BASE}/groups/${currentGroupId}/messages`;
    } else {
        return alert('Выберите чат');
    }
    
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            text: text || '', 
            attachments: pendingAttachments,
            reply_to: replyTo || null
        })
    });
    
    if (res.ok) {
        messageInput.value = '';
        pendingAttachments = [];
        clearReply();
        document.getElementById('previewArea').innerHTML = '';
        if (currentDialogId) {
            await loadMessages(currentDialogId);
            await fetch(`${API_BASE}/dialogs/${currentDialogId}/read`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } });
        } else if (currentGroupId) {
            await loadGroupMessages(currentGroupId);
        }
        await loadDialogs();
    } else {
        alert('Ошибка отправки');
    }
};

messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !sendBtn.disabled) sendBtn.click();
});

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, m => m === '&' ? '&amp;' : (m === '<' ? '&lt;' : '&gt;'));
}



// Мобильная навигация
const isMobile = () => window.innerWidth <= 768;
const dialogsSidebar = document.getElementById('dialogsSidebar');
const chatMain = document.getElementById('chatMain');
const chatMainHeader = document.getElementById('chatMainHeader');
const chatMainTitle = document.getElementById('chatMainTitle');
const mobileBackBtn = document.getElementById('mobileBackBtn');

function openChatMobile(name) {
    if (!isMobile()) return;
    chatMainTitle.textContent = name || '';
    chatMainHeader.style.display = 'flex';
    dialogsSidebar.classList.add('hidden-mobile');
    chatMain.classList.add('visible-mobile');
}

function closeChatMobile() {
    if (!isMobile()) return;
    dialogsSidebar.classList.remove('hidden-mobile');
    chatMain.classList.remove('visible-mobile');
    chatMainHeader.style.display = 'none';
}

mobileBackBtn.addEventListener('click', closeChatMobile);

// Поддержка
document.getElementById('supportBtn').onclick = () => {
    document.getElementById('supportModal').classList.add('active');
    document.getElementById('supportMessage').focus();
};

document.getElementById('supportCancel').onclick = () => {
    document.getElementById('supportModal').classList.remove('active');
    document.getElementById('supportMessage').value = '';
};

document.getElementById('supportModal').addEventListener('click', (e) => {
    if (e.target === document.getElementById('supportModal')) {
        document.getElementById('supportModal').classList.remove('active');
        document.getElementById('supportMessage').value = '';
    }
});

document.getElementById('supportSubmit').onclick = async () => {
    const message = document.getElementById('supportMessage').value.trim();
    if (!message) return;

    const submitBtn = document.getElementById('supportSubmit');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Отправляем...';

    try {
        const res = await fetch(`${API_BASE}/help?name=${encodeURIComponent(currentUser)}&message=${encodeURIComponent(message)}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (res.ok) {
            document.getElementById('supportModal').classList.remove('active');
            document.getElementById('supportMessage').value = '';
            alert('Сообщение отправлено! Мы скоро ответим.');
        } else {
            alert('Ошибка отправки, попробуйте позже.');
        }
    } catch(e) {
        alert('Ошибка сети, попробуйте позже.');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Отправить';
    }
};
(async function() {
    const savedToken = localStorage.getItem('token');
    const savedUser = localStorage.getItem('user');
    if (savedToken && savedUser) {
        token = savedToken;
        currentUser = savedUser;
        showChatPage();
    }
})();
