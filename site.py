#!/usr/bin/env python3
"""
⚛️ QUANTUM IA - Sistema Aberto
👥 Cadastro livre para todos
🤖 Trading automático na IQ Option
☁️ Railway Ready
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import deque
from flask import Flask, request, jsonify
from flask_cors import CORS

# ═══════════════════════════════════════════
# CONFIGURAÇÕES
# ═══════════════════════════════════════════
FUSO_BR = timezone(timedelta(hours=-3))
os.environ['TZ'] = 'America/Sao_Paulo'
time.tzset()

DB_PATH = "quantum_site.db"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# BANCO DE DADOS
# ═══════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            senha TEXT,
            nome TEXT,
            ativo INTEGER DEFAULT 1,
            iq_email TEXT DEFAULT '',
            iq_senha TEXT DEFAULT '',
            iq_conta TEXT DEFAULT 'PRACTICE',
            valor_entrada REAL DEFAULT 2.0,
            multiplicador REAL DEFAULT 2.0,
            max_gales INTEGER DEFAULT 1,
            stop_loss REAL DEFAULT 0,
            stop_win REAL DEFAULT 0,
            bot_ligado INTEGER DEFAULT 0,
            saldo REAL DEFAULT 0,
            criado_em TEXT
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            data TEXT,
            ativo TEXT,
            direcao TEXT,
            valor REAL,
            resultado TEXT,
            lucro REAL
        );
    """)
    conn.commit()
    conn.close()

def get_user_by_email(email):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    row = c.fetchone()
    cols = [d[0] for d in c.description] if c.description else []
    conn.close()
    return dict(zip(cols, row)) if row else None

def criar_usuario(email, senha, nome):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO users (email, senha, nome, ativo, criado_em) VALUES (?,?,?,1,datetime('now','localtime'))",
                     (email, senha, nome))
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

def user_ativo(email):
    u = get_user_by_email(email)
    return bool(u and u.get('ativo', 1))

def salvar_trade(user_id, ativo, direcao, valor, resultado, lucro):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO trades (user_id, data, ativo, direcao, valor, resultado, lucro) VALUES (?,?,?,?,?,?,?)",
                 (user_id, datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S"), ativo, direcao, valor, resultado, lucro))
    conn.commit()
    conn.close()

def resultado_dia(user_id):
    hoje = datetime.now(FUSO_BR).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT COUNT(*), SUM(CASE WHEN resultado='win' THEN 1 ELSE 0 END), 
                        SUM(CASE WHEN resultado='loss' THEN 1 ELSE 0 END), SUM(lucro) 
                 FROM trades WHERE user_id=? AND data LIKE ?""", (user_id, f"{hoje}%"))
    t, w, l, lc = c.fetchone()
    conn.close()
    return {"total": t or 0, "wins": w or 0, "losses": l or 0, "lucro": lc or 0.0}

# ═══════════════════════════════════════════
# 5 ESTRATÉGIAS ORIGINAIS
# ═══════════════════════════════════════════

class Mortalha:
    def sma(self, d, p):
        try:
            if len(d)>=p: return sum(d[-p:])/p
            return sum(d)/len(d) if d else 0
        except: return 0
    def wma(self, d, p):
        try:
            if len(d)<p: return sum(d)/len(d) if d else 0
            w=np.arange(1, p+1); return np.sum(np.array(d[-p:])*w)/np.sum(w)
        except: return 0
    def analisar(self, v):
        try:
            if len(v)<30: return None, 0
            c=np.array([x['close'] for x in v]); b1=np.zeros(len(c))
            for i in range(len(c)):
                if i>=33: b1[i]=self.sma(c[:i+1], 1)-self.sma(c[:i+1], 34)
            b2=np.zeros(len(b1))
            for i in range(len(b1)):
                if i>=3: b2[i]=self.wma(b1[:i+1], 4)
            if b1[-1]>b2[-1] and b1[-2]<=b2[-2]: return'CALL', min(45+abs(b1[-1]-b2[-1])*10000, 90)
            if b1[-1]<b2[-1] and b1[-2]>=b2[-2]: return'PUT', min(45+abs(b1[-1]-b2[-1])*10000, 90)
            return None, 0
        except: return None, 0

class Formiga:
    def ema(self, p, pe):
        try:
            if len(p)<pe: return sum(p)/len(p) if p else 0
            return np.mean(p[-pe:])
        except: return 0
    def analisar(self, v):
        try:
            if len(v)<15: return None, 0
            precos=np.array([x['close'] for x in v])
            ema5=self.ema(precos, 5); ema10=self.ema(precos, 10)
            dif=((ema5-ema10)/ema10)*100 if ema10>0 else 0
            sc=sp=0
            if dif>0.02: sc+=3
            elif dif>0.005: sc+=1
            elif dif<-0.02: sp+=3
            elif dif<-0.005: sp+=1
            if sc>=2 and sc>sp: return'CALL', min(50+sc*4, 85)
            if sp>=2 and sp>sc: return'PUT', min(50+sp*4, 85)
            return None, 0
        except: return None, 0

class Fortaleza:
    def rsi(self, p, pe=7):
        try:
            if len(p)<pe+1: return 50
            d=np.diff(list(p[-pe-1:])); g=np.where(d>0, d, 0); l=np.where(d<0, -d, 0)
            mg=np.mean(g) if len(g)>0 else 0; mp=np.mean(l) if len(l)>0 else 0
            if mp==0: return 100
            return 100-(100/(1+mg/mp))
        except: return 50
    def analisar(self, v):
        try:
            if len(v)<18: return None, 0
            precos=np.array([x['close'] for x in v])
            rsi_val=self.rsi(precos)
            m=np.mean(precos[-10:]) if len(precos)>=10 else np.mean(precos)
            s=np.std(precos[-10:]) if len(precos)>=10 else 0
            bs=m+2*s; bi=m-2*s
            sc=sp=0
            if rsi_val<30: sc+=3
            elif rsi_val<40: sc+=2
            if rsi_val>70: sp+=3
            elif rsi_val>60: sp+=2
            if precos[-1]<=bi*1.0004: sc+=3
            if precos[-1]>=bs*0.9996: sp+=3
            if sc>=4 and sc>sp: return'CALL', min(60+sc*3, 90)
            if sp>=4 and sp>sc: return'PUT', min(60+sp*3, 90)
            return None, 0
        except: return None, 0

class RaioNegro:
    def analisar(self, v):
        try:
            if len(v)<12: return None, 0
            precos=np.array([x['close'] for x in v])
            ema5=np.mean(precos[-5:]) if len(precos)>=5 else precos[-1]
            ema13=np.mean(precos[-13:]) if len(precos)>=13 else ema5
            macd=ema5-ema13; sinal=macd*0.5
            mom=precos[-1]-precos[-3] if len(precos)>=3 else 0
            sc=sp=0
            if macd>sinal and macd>0: sc+=3
            elif macd>sinal: sc+=1
            elif macd<sinal and macd<0: sp+=3
            elif macd<sinal: sp+=1
            if mom>0.00003: sc+=3
            elif mom>0: sc+=1
            elif mom<-0.00003: sp+=3
            elif mom<0: sp+=1
            if sc>=2 and sc>sp: return'CALL', min(48+sc*4, 85)
            if sp>=2 and sp>sc: return'PUT', min(48+sp*4, 85)
            return None, 0
        except: return None, 0

class Tsunami:
    def analisar(self, v):
        try:
            if len(v)<12: return None, 0
            precos=np.array([x['close'] for x in v])
            altas=sum(1 for i in range(-min(5, len(v)-1), 0) if precos[i]>precos[i-1])
            sc=sp=0
            if altas>=3: sc+=3
            elif altas<=2: sp+=3
            if sc>=2 and sc>sp: return'CALL', min(50+sc*3, 85)
            if sp>=2 and sp>sc: return'PUT', min(50+sp*3, 85)
            return None, 0
        except: return None, 0

class QuantumIA:
    def __init__(self):
        self.mortalha=Mortalha(); self.formiga=Formiga(); self.fortaleza=Fortaleza()
        self.raio_negro=RaioNegro(); self.tsunami=Tsunami(); self.min_estrategias=3
    def analisar_completo(self, v):
        try:
            if len(v)<30: return None, 0, 0
            resultados=[]; votos={'CALL':0, 'PUT':0}; confiancas={'CALL':[], 'PUT':[]}
            for est in [self.mortalha, self.formiga, self.fortaleza, self.raio_negro, self.tsunami]:
                try:
                    d, c=est.analisar(v)
                    if d: resultados.append(d); votos[d]+=1; confiancas[d].append(c)
                except: pass
            total=len(resultados)
            if total<self.min_estrategias: return None, 0, total
            if votos['CALL']>=self.min_estrategias and votos['CALL']>votos['PUT']:
                conf=np.mean(confiancas['CALL']); return'CALL', min(conf+(total-3)*4, 95), total
            if votos['PUT']>=self.min_estrategias and votos['PUT']>votos['CALL']:
                conf=np.mean(confiancas['PUT']); return'PUT', min(conf+(total-3)*4, 95), total
            return None, 0, total
        except: return None, 0, 0
    def melhor_par(self, velas_dict, bloqueados):
        melhor=None; melhor_score=0
        for nome, velas in velas_dict.items():
            if nome in bloqueados: continue
            if len(velas)>=30:
                d, cf, num=self.analisar_completo(velas)
                if d:
                    score=cf+(num*5)
                    if score>melhor_score: melhor_score=score; melhor={'ativo': nome, 'direcao': d, 'confianca': cf, 'estrategias': num}
        return melhor

# ═══════════════════════════════════════════
# IQ OPTION API
# ═══════════════════════════════════════════

class IQAPI:
    def __init__(self, email, senha, conta='PRACTICE'):
        self.email = email; self.senha = senha; self.conta = conta
        self.api = None
        self.velas = {nome: deque(maxlen=100) for nome in ["EURUSD","GBPUSD","EURGBP"]}
        self.ok = False
        self.ativo_map = {"EURUSD":"EURUSD-OTC", "GBPUSD":"GBPUSD-OTC", "EURGBP":"EURGBP-OTC"}

    def conectar(self):
        from iqoptionapi.stable_api import IQ_Option
        try:
            self.api = IQ_Option(self.email, self.senha)
            ok, _ = self.api.connect()
            if ok:
                self.api.change_balance(self.conta)
                self.ok = True
                return True, self.api.get_balance()
            return False, 0
        except: return False, 0

    def atualizar_velas(self):
        if not self.ok: return
        for nome, ativo_id in self.ativo_map.items():
            try:
                c = self.api.get_candles(ativo_id, 60, 80, time.time())
                if c and len(c) > 0:
                    self.velas[nome].clear()
                    for x in c[-80:]:
                        if isinstance(x, dict):
                            self.velas[nome].append({
                                'time': datetime.fromtimestamp(x.get('from', 0), FUSO_BR),
                                'open': float(x['open']), 'high': float(x['max']),
                                'low': float(x['min']), 'close': float(x['close']),
                                'volume': int(x.get('volume', 0))
                            })
            except: pass

    def get_saldo(self):
        if not self.ok or not self.api: return 0
        try: return float(self.api.get_balance())
        except: return 0

    def comprar(self, ativo, direcao, exp, valor):
        if not self.ok: return False, None
        ativo_id = self.ativo_map.get(ativo, ativo)
        try:
            ok, order_id = self.api.buy(valor, ativo_id, direcao.lower(), exp)
            return ok, order_id
        except: return False, None

# ═══════════════════════════════════════════
# MOTOR DE TRADING
# ═══════════════════════════════════════════

def trading_loop():
    logger.info("🔄 Motor de trading iniciado")
    user_bots = {}
    
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, iq_email, iq_senha, iq_conta, valor_entrada, multiplicador, max_gales FROM users WHERE bot_ligado=1 AND ativo=1")
            usuarios_ativos = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
            conn.close()
            
            for user in usuarios_ativos:
                uid = user['id']
                if not user.get('iq_email'): continue
                
                if uid not in user_bots or not user_bots[uid].ok:
                    iq = IQAPI(user['iq_email'], user['iq_senha'], user['iq_conta'])
                    ok, saldo = iq.conectar()
                    if ok:
                        user_bots[uid] = iq
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute("UPDATE users SET saldo=? WHERE id=?", (saldo, uid))
                        conn.commit()
                        conn.close()
                    else:
                        time.sleep(10)
                        continue
                
                iq = user_bots[uid]
                if not iq.ok: continue
                
                iq.atualizar_velas()
                m = QuantumIA()
                sinal = m.melhor_par(iq.velas, [])
                
                if sinal:
                    valor = user['valor_entrada']
                    max_gales = user['max_gales']
                    multiplicador = user['multiplicador']
                    
                    for tentativa in range(max_gales + 1):
                        val = round(valor * (multiplicador ** tentativa), 2)
                        saldo_antes = iq.get_saldo()
                        ok, _ = iq.comprar(sinal['ativo'], sinal['direcao'], 1, val)
                        if not ok: continue
                        
                        time.sleep(65)
                        saldo_depois = iq.get_saldo()
                        lucro = saldo_depois - saldo_antes
                        
                        if lucro > 0:
                            salvar_trade(uid, sinal['ativo'], sinal['direcao'], val, "win", abs(lucro))
                            conn = sqlite3.connect(DB_PATH)
                            conn.execute("UPDATE users SET saldo=? WHERE id=?", (saldo_depois, uid))
                            conn.commit()
                            conn.close()
                            break
                        elif lucro < 0:
                            if tentativa < max_gales: continue
                            salvar_trade(uid, sinal['ativo'], sinal['direcao'], val, "loss", -val)
                            conn = sqlite3.connect(DB_PATH)
                            conn.execute("UPDATE users SET saldo=? WHERE id=?", (saldo_depois, uid))
                            conn.commit()
                            conn.close()
                        break
                
                time.sleep(5)
            
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"Erro trading: {e}")
            time.sleep(30)

# ═══════════════════════════════════════════
# FLASK APP
# ═══════════════════════════════════════════

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

@app.route('/api/cadastrar', methods=['POST'])
def api_cadastrar():
    data = request.json
    email = data.get('email', '').strip()
    senha = data.get('senha', '').strip()
    nome = data.get('nome', email.split('@')[0]).strip()
    
    if not email or not senha:
        return jsonify({"status": "erro", "msg": "Email e senha obrigatórios"}), 400
    
    if get_user_by_email(email):
        return jsonify({"status": "erro", "msg": "Email já cadastrado"}), 400
    
    if criar_usuario(email, senha, nome):
        return jsonify({"status": "ok", "msg": "Conta criada com sucesso!"})
    return jsonify({"status": "erro", "msg": "Erro ao criar conta"}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    u = get_user_by_email(data['email'])
    if u and u['senha'] == data['senha'] and user_ativo(data['email']):
        return jsonify({"status": "ok", "user": {"id": u['id'], "email": u['email'], "nome": u['nome']}})
    return jsonify({"status": "erro", "msg": "Email ou senha inválidos"}), 401

@app.route('/api/status', methods=['POST'])
def api_status():
    u = get_user_by_email(request.json['email'])
    if not u: return jsonify({"status": "erro"}), 404
    res = resultado_dia(u['id'])
    return jsonify({
        "bot_ligado": bool(u.get('bot_ligado', 0)),
        "saldo": u.get('saldo', 0),
        "hoje": res,
        "config": {
            "iq_email": u.get('iq_email', ''),
            "iq_conta": u.get('iq_conta', 'PRACTICE'),
            "valor_entrada": u.get('valor_entrada', 2.0),
            "multiplicador": u.get('multiplicador', 2.0),
            "max_gales": u.get('max_gales', 1),
            "stop_loss": u.get('stop_loss', 0),
            "stop_win": u.get('stop_win', 0)
        }
    })

@app.route('/api/config', methods=['POST'])
def api_config():
    data = request.json
    email = data.pop('email', None)
    if not email: return jsonify({"status": "erro"}), 400
    conn = sqlite3.connect(DB_PATH)
    sets = ", ".join(f"{k}=?" for k in data)
    vals = list(data.values()) + [email]
    conn.execute(f"UPDATE users SET {sets} WHERE email=?", vals)
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/ligar', methods=['POST'])
def api_ligar():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET bot_ligado=1 WHERE email=?", (request.json['email'],))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/desligar', methods=['POST'])
def api_desligar():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET bot_ligado=0 WHERE email=?", (request.json['email'],))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/historico', methods=['POST'])
def api_historico():
    u = get_user_by_email(request.json['email'])
    if not u: return jsonify([])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, ativo, direcao, valor, resultado, lucro FROM trades WHERE user_id=? ORDER BY id DESC LIMIT 50", (u['id'],))
    rows = [{"data": r[0], "ativo": r[1], "direcao": r[2], "valor": r[3], "resultado": r[4], "lucro": r[5]} for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

# ═══════════════════════════════════════════
# INICIAR
# ═══════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    threading.Thread(target=trading_loop, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=5000)
