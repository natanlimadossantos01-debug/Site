from flask import Flask, render_template_string

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>⚛️ Quantum IA</title>
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    <link rel="manifest" href="/manifest.json">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #fff; font-family: Arial; padding: 15px; max-width: 500px; margin: 0 auto; }
        .header { text-align: center; padding: 20px; background: linear-gradient(45deg, #6c00ff, #00d4ff); border-radius: 15px; margin-bottom: 15px; }
        .header h1 { font-size: 24px; }
        .card { background: #1a1a1a; border-radius: 15px; padding: 15px; margin-bottom: 10px; }
        .card h3 { color: #00d4ff; margin-bottom: 10px; }
        .status { font-size: 20px; font-weight: bold; padding: 10px; border-radius: 10px; text-align: center; margin: 10px 0; }
        .online { background: #00ff8822; color: #00ff88; }
        .offline { background: #ff004422; color: #ff4444; }
        .row { display: flex; gap: 10px; margin: 10px 0; }
        .btn { flex: 1; padding: 15px; border: none; border-radius: 10px; font-size: 14px; font-weight: bold; cursor: pointer; color: white; }
        .btn-success { background: #00ff88; color: #000; }
        .btn-danger { background: #ff4444; }
        .btn-primary { background: #6c00ff; }
        .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .stat { background: #252525; padding: 15px; border-radius: 10px; text-align: center; }
        .stat .value { font-size: 20px; font-weight: bold; color: #00d4ff; }
        .stat .label { font-size: 11px; color: #888; }
        input, select { width: 100%; padding: 12px; background: #252525; border: 1px solid #333; border-radius: 10px; color: white; font-size: 14px; margin: 5px 0; }
        label { color: #888; font-size: 12px; display: block; margin-top: 8px; }
        .hidden { display: none; }
        .tab-bar { display: flex; margin-bottom: 15px; background: #1a1a1a; border-radius: 10px; overflow: hidden; }
        .tab { flex: 1; padding: 12px; text-align: center; cursor: pointer; font-weight: bold; font-size: 11px; border: none; background: transparent; color: #888; }
        .tab.active { background: #6c00ff; color: white; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .saved { background: #00ff8822; color: #00ff88; padding: 10px; border-radius: 10px; text-align: center; margin: 10px 0; display: none; }
    </style>
</head>
<body>
    <div class="header"><h1>⚛️ QUANTUM IA</h1><p>Painel de Controle</p></div>
    
    <div class="tab-bar">
        <button class="tab active" onclick="showTab('dashboard')">📊 Painel</button>
        <button class="tab" onclick="showTab('config')">⚙️ Config</button>
        <button class="tab" onclick="showTab('admin')">👑 Admin</button>
    </div>

    <div id="tab-dashboard" class="tab-content active">
        <div class="card"><h3>🤖 Status</h3>
            <div id="statusBot" class="status">🔴 DESLIGADO</div>
            <div class="row">
                <button class="btn btn-success" onclick="ligar()">▶️ LIGAR</button>
                <button class="btn btn-danger" onclick="desligar()">⏹️ DESLIGAR</button>
            </div>
        </div>
        <div class="card"><h3>📊 Hoje</h3>
            <div class="stats">
                <div class="stat"><div class="value" id="totalOps">0</div><div class="label">Operações</div></div>
                <div class="stat"><div class="value" id="totalWins">0</div><div class="label">✅ Wins</div></div>
                <div class="stat"><div class="value" id="totalLosses">0</div><div class="label">❌ Losses</div></div>
                <div class="stat"><div class="value" id="totalLucro">R$ 0</div><div class="label">💰 Lucro</div></div>
            </div>
        </div>
    </div>

    <div id="tab-config" class="tab-content">
        <div class="card"><h3>💹 IQ Option</h3>
            <label>📧 Email</label><input type="email" id="cfg_email" placeholder="seuemail@gmail.com">
            <label>🔒 Senha</label><input type="password" id="cfg_senha" placeholder="Sua senha IQ">
            <label>📊 Conta</label><select id="cfg_conta"><option value="PRACTICE">🎯 DEMO</option><option value="REAL">💰 REAL</option></select>
        </div>
        <div class="card"><h3>💰 Valores</h3>
            <label>💵 Entrada (R$)</label><input type="number" id="cfg_valor" placeholder="2.00" step="0.5">
            <label>🔄 Multiplicador</label><input type="number" id="cfg_multi" placeholder="2.0" step="0.1">
            <label>🎯 Max Gales</label><input type="number" id="cfg_gales" placeholder="1">
        </div>
        <div class="card"><h3>🛑 Stops</h3>
            <label>🔴 Stop Loss</label><input type="number" id="cfg_sl" placeholder="0">
            <label>🟢 Stop Win</label><input type="number" id="cfg_sw" placeholder="0">
        </div>
        <div id="savedMsg" class="saved">✅ Salvo!</div>
        <button class="btn btn-success" onclick="salvarConfig()" style="width:100%">💾 SALVAR</button>
    </div>

    <div id="tab-admin" class="tab-content">
        <div class="card"><h3>🔑 Código Admin</h3>
            <input type="password" id="adminCode" placeholder="Digite o código">
            <button class="btn btn-primary" onclick="verificarAdmin()" style="width:100%;margin-top:10px">🔓 ACESSAR</button>
        </div>
    </div>

    <script>
        function showTab(t) {
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(x => x.classList.remove('active'));
            document.querySelector(`[onclick="showTab('${t}')"]`).classList.add('active');
            document.getElementById(`tab-${t}`).classList.add('active');
        }

        function verificarAdmin() {
            if (document.getElementById("adminCode").value === "QUANTUMBOT") {
                alert("Admin liberado!");
            } else {
                alert("Código incorreto!");
            }
        }

        function ligar() {
            document.getElementById("statusBot").className = "status online";
            document.getElementById("statusBot").innerHTML = "🟢 ONLINE";
        }

        function desligar() {
            document.getElementById("statusBot").className = "status offline";
            document.getElementById("statusBot").innerHTML = "🔴 DESLIGADO";
        }

        function salvarConfig() {
            document.getElementById("savedMsg").style.display = "block";
            setTimeout(() => document.getElementById("savedMsg").style.display = "none", 2000);
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/manifest.json')
def manifest():
    return {
        "name": "Quantum IA",
        "short_name": "QuantumIA",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0a",
        "theme_color": "#6c00ff"
    }

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
