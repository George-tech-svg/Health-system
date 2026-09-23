from flask import Flask, session, render_template_string, jsonify, request
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "test-key"

# Simple HTML template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Read Receipts Demo</title>
    <style>
        body { font-family: Arial; max-width: 600px; margin: 50px auto; padding: 20px; }
        .message { padding: 10px; margin: 10px 0; border-radius: 10px; max-width: 80%; }
        .sent { background: #dcf8c5; margin-left: auto; text-align: right; }
        .received { background: white; border: 1px solid #ddd; }
        .status { font-size: 11px; margin-top: 5px; }
        .sent-status { color: gray; }
        .delivered-status { color: orange; }
        .read-status { color: green; font-weight: bold; }
        input, button { padding: 10px; margin: 5px; }
        input { width: 70%; }
        button { cursor: pointer; }
    </style>
</head>
<body>
    <h2>💬 Read Receipts Demo</h2>
    <div id="messages" style="border: 1px solid #ccc; height: 400px; overflow-y: auto; padding: 10px; background: #efeae2;"></div>
    
    <div style="margin-top: 20px;">
        <input type="text" id="messageInput" placeholder="Type a message...">
        <button onclick="sendMessage()">Send</button>
        <button onclick="loadMessages()">Refresh</button>
    </div>
    
    <div style="margin-top: 10px; font-size: 12px; color: #666;">
        <strong>Status meanings:</strong><br>
        ✓ SENT (gray) = Message sent<br>
        ✓✓ DELIVERED (orange) = Message delivered to receiver's chat<br>
        ✓✓ READ (green) = Receiver has viewed the message
    </div>

    <script>
        async function loadMessages() {
            const response = await fetch('/api/messages');
            const messages = await response.json();
            
            const container = document.getElementById('messages');
            container.innerHTML = '';
            
            messages.forEach(msg => {
                const div = document.createElement('div');
                div.className = `message ${msg.direction === 'outgoing' ? 'sent' : 'received'}`;
                
                let statusHtml = '';
                if (msg.direction === 'outgoing') {
                    if (msg.is_read === 1) {
                        statusHtml = '<div class="status read-status">✓✓ READ</div>';
                    } else if (msg.is_delivered === 1) {
                        statusHtml = '<div class="status delivered-status">✓✓ DELIVERED</div>';
                    } else {
                        statusHtml = '<div class="status sent-status">✓ SENT</div>';
                    }
                }
                
                div.innerHTML = `
                    <div>${msg.content}</div>
                    ${statusHtml}
                    <div style="font-size: 10px; color: #999;">${new Date(msg.timestamp).toLocaleTimeString()}</div>
                `;
                container.appendChild(div);
            });
            container.scrollTop = container.scrollHeight;
        }
        
        async function sendMessage() {
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if (!text) return;
            
            const response = await fetch('/api/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: text})
            });
            
            if (response.ok) {
                input.value = '';
                loadMessages();
                // Simulate delivery after 1 second
                setTimeout(() => {
                    fetch('/api/simulate_delivery', {method: 'POST'});
                    loadMessages();
                }, 1000);
                // Simulate read after 3 seconds
                setTimeout(() => {
                    fetch('/api/simulate_read', {method: 'POST'});
                    loadMessages();
                }, 3000);
            }
        }
        
        loadMessages();
        setInterval(loadMessages, 2000);
    </script>
</body>
</html>
'''

# Initialize database
def init_db():
    conn = sqlite3.connect('demo.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  content TEXT,
                  direction TEXT,
                  is_delivered INTEGER DEFAULT 0,
                  is_read INTEGER DEFAULT 0,
                  timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/messages')
def get_messages():
    conn = sqlite3.connect('demo.db')
    c = conn.cursor()
    c.execute("SELECT id, content, direction, is_delivered, is_read, timestamp FROM messages ORDER BY id ASC")
    messages = [{'id': row[0], 'content': row[1], 'direction': row[2], 
                 'is_delivered': row[3], 'is_read': row[4], 'timestamp': row[5]} 
                for row in c.fetchall()]
    conn.close()
    return jsonify(messages)

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    import datetime
    conn = sqlite3.connect('demo.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (content, direction, timestamp) VALUES (?, 'outgoing', ?)",
              (data['message'], datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'sent'})

@app.route('/api/simulate_delivery', methods=['POST'])
def simulate_delivery():
    conn = sqlite3.connect('demo.db')
    c = conn.cursor()
    c.execute("UPDATE messages SET is_delivered = 1 WHERE direction = 'outgoing' AND is_delivered = 0 ORDER BY id DESC LIMIT 1")
    conn.commit()
    conn.close()
    return jsonify({'status': 'delivered'})

@app.route('/api/simulate_read', methods=['POST'])
def simulate_read():
    conn = sqlite3.connect('demo.db')
    c = conn.cursor()
    c.execute("UPDATE messages SET is_read = 1 WHERE direction = 'outgoing' AND is_read = 0 ORDER BY id DESC LIMIT 1")
    conn.commit()
    conn.close()
    return jsonify({'status': 'read'})

if __name__ == '__main__':
    print("\n" + "="*50)
    print("READ RECEIPTS DEMO")
    print("="*50)
    print("\nOpen: http://localhost:5001")
    print("\nWatch the status change:")
    print("  - Send a message → shows ✓ SENT")
    print("  - After 1 sec → shows ✓✓ DELIVERED")  
    print("  - After 3 sec → shows ✓✓ READ")
    print("="*50 + "\n")
    app.run(debug=True, port=5001)