#!/usr/bin/env python3
"""
⚛️ QUANTUM IA - Site Completo (Web App)
👨‍🏫 Estratégia Original do Trader Professor
👥 Multi-usuário com painel admin
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
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import requests as req_http  # para requisições HTTP do próprio Flask (não usado no core)

# ═══════════════════════════════════════════
# CONFIGURAÇÕES GERAIS
# ═══════════════════════════════════════════
FUSO_BR = timezone(timedelta(hours=-3))
os.environ['TZ'] = 'America/Sao_Paulo'
time.tzset()

SENHA_ADMIN = os.environ.get('SENHA_ADMIN', 'admin123')
DB_PATH = "quantum_site.db"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# BANCO DE DADOS (MULTI-USUÁRIO)
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
            expiracao TEXT,
            admin INTEGER DEFAULT 0,
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
    # Admin padrão
    admin_exp = (datetime.now(FUSO_BR) + timedelta(days=36500)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT OR IGNORE INTO users (email, senha, nome, ativo, admin, expiracao, criado_em) VALUES ('admin@quantum.com', ?, 'Administrador', 1, 1, ?, datetime('now','localtime'))",
                 (SENHA_ADMIN, admin_exp))
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

def get_user_by_id(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    cols = [d[0] for d in c.description] if c.description else []
    conn.close()
    return dict(zip(cols, row)) if row else None

def criar_usuario(email, nome, dias=3):
    exp = (datetime.now(FUSO_BR) + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO users (email, senha, nome, ativo, expiracao, criado_em) VALUES (?, '123456', ?, 1, ?, ?)",
                     (email, nome, exp, now))
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

def ativar_user(email, dias=30):
    exp = (datetime.now(FUSO_BR) + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=1, expiracao=? WHERE email=?", (exp, email))
    conn.commit()
    conn.close()

def desativar_user(email):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=0, bot_ligado=0 WHERE email=?", (email,))
    conn.commit()
    conn.close()

def user_ativo(email):
    u = get_user_by_email(email)
    if not u: return False
    if u['admin']: return True
    try:
        exp = datetime.strptime(u['expiracao'], "%Y-%m-%d %H:%M:%S")
        if datetime.now(FUSO_BR) > exp:
            desativar_user(email)
            return False
        return True
    except:
        return False

def listar_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, email, nome, ativo, expiracao, bot_ligado, saldo FROM users ORDER BY criado_em DESC")
    rows = [{"id": r[0], "email": r[1], "nome": r[2], "ativo": r[3], "exp": r[4] or "", "bot": r[5], "saldo": r[6] or 0} for r in c.fetchall()]
    conn.close()
    return rows

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
# 5 ESTRATÉGIAS ORIGINAIS (TRADER PROFESSOR)
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
# MOTOR DE TRADING (BACKGROUND)
# ═══════════════════════════════════════════

def trading_loop():
    """Verifica todos os usuários com bot ligado e opera para cada um"""
    logger.info("🔄 Motor de trading iniciado")
    user_bots = {}  # user_id -> IQAPI
    
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, email, iq_email, iq_senha, iq_conta, valor_entrada, multiplicador, max_gales, stop_loss, stop_win FROM users WHERE bot_ligado=1 AND ativo=1")
            usuarios_ativos = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
            conn.close()
            
            for user in usuarios_ativos:
                uid = user['id']
                email = user['email']
                if not user_ativo(email):
                    continue
                
                # Conectar ou obter API existente
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
                if not iq.ok:
                    continue
                
                iq.atualizar_velas()
                m = QuantumIA()
                sinal = m.melhor_par(iq.velas, [])
                
                if sinal:
                    logger.info(f"📡 User {uid}: {sinal['ativo']} {sinal['direcao']} {sinal['confianca']:.0f}%")
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
                
                time.sleep(5)  # pequeno intervalo entre usuários
            
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"Erro no loop de trading: {e}")
            time.sleep(30)

# ═══════════════════════════════════════════
# FLASK APP (SITE)
# ═══════════════════════════════════════════

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

# HTML do site (mesmo frontend, mas agora com login multi-usuário)
HTML = """
<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>⚛️ Quantum IA</title>
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
        .log { background: #111; border-radius: 10px; padding: 10px; max-height: 150px; overflow-y: auto; font-size: 11px; font-family: monospace; }
    </style>
</head>
<body>
    <div id="loginScreen">
        <div class="header"><h1>⚛️ QUANTUM IA</h1><p>Painel de Controle</p></div>
        <div class="card">
            <h3>🔐 Login</h3>
            <input type="email" id="loginEmail" placeholder="Email">
            <input type="password" id="loginSenha" placeholder="Senha">
            <button class="btn btn-success" onclick="login()" style="width:100%;margin-top:10px">▶️ ENTRAR</button>
        </div>
    </div>

    <div id="mainScreen" class="hidden">
        <div class="header"><h1>⚛️ QUANTUM IA</h1><p id="saldoDisplay">💰 Carregando...</p></div>
        
        <div class="tab-bar">
            <button class="tab active" onclick="showTab('dashboard')">📊 Painel</button>
            <button class="tab" onclick="showTab('config')">⚙️ Config</button>
            <button class="tab" onclick="showTab('historico')">📋 Histórico</button>
            <button class="tab admin-only hidden" id="tabAdmin" onclick="showTab('admin')">👑 Admin</button>
        </div>

        <div id="tab-dashboard" class="tab-content active">
            <div class="card"><h3>🤖 Status</h3>
                <div id="statusBot" class="status">🔄 Carregando...</div>
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
                <label>💵 Entrada (R$)</label><input type="number" id="cfg_valor" step="0.5">
                <label>🔄 Multiplicador</label><input type="number" id="cfg_multi" step="0.1">
                <label>🎯 Max Gales</label><input type="number" id="cfg_gales">
            </div>
            <div class="card"><h3>🛑 Stops</h3>
                <label>🔴 Stop Loss</label><input type="number" id="cfg_sl">
                <label>🟢 Stop Win</label><input type="number" id="cfg_sw">
            </div>
            <div id="savedMsg" class="saved">✅ Salvo!</div>
            <button class="btn btn-success" onclick="salvarConfig()" style="width:100%">💾 SALVAR</button>
        </div>

        <div id="tab-historico" class="tab-content">
            <div class="card"><h3>📋 Operações</h3><div class="log" id="historicoList" style="max-height:400px">Carregando...</div></div>
        </div>

        <div id="tab-admin" class="tab-content">
            <div class="card"><h3>👑 Gerenciar Acessos</h3>
                <input type="email" id="adminEmail" placeholder="Email do cliente">
                <div class="row">
                    <input type="number" id="adminDias" placeholder="Dias" value="30" style="flex:1">
                    <button class="btn btn-success" onclick="adminAtivar()" style="flex:1">✅ ATIVAR</button>
                </div>
                <button class="btn btn-danger" onclick="adminDesativar()" style="width:100%;margin-top:5px">🚫 DESATIVAR</button>
            </div>
            <div class="card"><h3>👥 Usuários</h3><div id="adminLista">Carregando...</div></div>
        </div>

        <button class="btn btn-danger" onclick="logout()" style="width:100%;margin-top:15px">🚪 SAIR</button>
    </div>

    <script>
        let userData = JSON.parse(localStorage.getItem("qt_user"));
        let isAdmin = userData?.admin || false;
        if (userData) showMain();

        async function login() {
            const resp = await fetch('/api/login', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: document.getElementById('loginEmail').value, senha: document.getElementById('loginSenha').value})
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                userData = data.user;
                localStorage.setItem('qt_user', JSON.stringify(userData));
                isAdmin = userData.admin;
                showMain();
            } else { alert(data.msg); }
        }

        function showMain() {
            document.getElementById('loginScreen').classList.add('hidden');
            document.getElementById('mainScreen').classList.remove('hidden');
            if (isAdmin) document.getElementById('tabAdmin').classList.remove('hidden');
            carregarDados();
        }

        function logout() { localStorage.clear(); location.reload(); }

        function showTab(t) {
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(x => x.classList.remove('active'));
            document.querySelector(`[onclick="showTab('${t}')"]`).classList.add('active');
            document.getElementById(`tab-${t}`).classList.add('active');
            if (t === 'admin') carregarAdmin();
            if (t === 'historico') carregarHistorico();
        }

        async function carregarDados() {
            try {
                const resp = await fetch('/api/status', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email: userData.email})
                });
                const data = await resp.json();
                document.getElementById('statusBot').className = data.bot_ligado ? 'status online' : 'status offline';
                document.getElementById('statusBot').innerHTML = data.bot_ligado ? '🟢 ONLINE' : '🔴 DESLIGADO';
                document.getElementById('saldoDisplay').innerHTML = `💰 Saldo: R$ ${(data.saldo||0).toFixed(2)}`;
                document.getElementById('totalOps').innerText = data.hoje.total;
                document.getElementById('totalWins').innerText = data.hoje.wins;
                document.getElementById('totalLosses').innerText = data.hoje.losses;
                document.getElementById('totalLucro').innerText = `R$ ${data.hoje.lucro.toFixed(2)}`;
                document.getElementById('cfg_email').value = data.config.iq_email || '';
                document.getElementById('cfg_conta').value = data.config.iq_conta || 'PRACTICE';
                document.getElementById('cfg_valor').value = data.config.valor_entrada || 2;
                document.getElementById('cfg_multi').value = data.config.multiplicador || 2;
                document.getElementById('cfg_gales').value = data.config.max_gales || 1;
                document.getElementById('cfg_sl').value = data.config.stop_loss || 0;
                document.getElementById('cfg_sw').value = data.config.stop_win || 0;
            } catch(e) {}
        }

        async function ligar() {
            await fetch('/api/ligar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: userData.email})});
            carregarDados();
        }
        async function desligar() {
            await fetch('/api/desligar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: userData.email})});
            carregarDados();
        }

        async function salvarConfig() {
            await fetch('/api/config', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
                email: userData.email,
                iq_email: document.getElementById('cfg_email').value,
                iq_senha: document.getElementById('cfg_senha').value,
                iq_conta: document.getElementById('cfg_conta').value,
                valor_entrada: parseFloat(document.getElementById('cfg_valor').value),
                multiplicador: parseFloat(document.getElementById('cfg_multi').value),
                max_gales: parseInt(document.getElementById('cfg_gales').value),
                stop_loss: parseFloat(document.getElementById('cfg_sl').value),
                stop_win: parseFloat(document.getElementById('cfg_sw').value)
            })});
            document.getElementById('savedMsg').style.display = 'block';
            setTimeout(() => document.getElementById('savedMsg').style.display = 'none', 2000);
        }

        async function carregarHistorico() {
            const resp = await fetch('/api/historico', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: userData.email})});
            const data = await resp.json();
            document.getElementById('historicoList').innerHTML = data.length ? data.map(o => `<div style="margin:5px 0;padding:8px;background:#252525;border-radius:8px;border-left:3px solid ${o.resultado==='win'?'#00ff88':'#ff4444'}">${o.resultado==='win'?'✅':'❌'} ${o.ativo} ${o.direcao} | R$ ${(o.lucro||0).toFixed(2)}</div>`).join('') : 'Nenhuma operação.';
        }

        async function carregarAdmin() {
            const resp = await fetch('/api/admin/usuarios', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: userData.email})});
            const data = await resp.json();
            document.getElementById('adminLista').innerHTML = data.length ? data.map(u => `<div style="padding:10px;background:#252525;border-radius:8px;margin:5px 0;font-size:12px;display:flex;justify-content:space-between"><div><b>${u.nome||'Sem nome'}</b><br><span style="color:#888">${u.email}</span></div><span class="${u.ativo?'badge-active':'badge-expired'}" style="padding:4px 8px;border-radius:5px;font-size:10px;font-weight:bold;background:${u.ativo?'#00ff8822':'#ff004422'};color:${u.ativo?'#00ff88':'#ff4444'}">${u.ativo?'ATIVO':'EXPIRADO'}</span></div>`).join('') : 'Nenhum usuário.';
        }

        async function adminAtivar() {
            const email = document.getElementById('adminEmail').value;
            const dias = document.getElementById('adminDias').value || 30;
            if (!email) return alert('Digite o email!');
            await fetch('/api/admin/ativar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({admin_email: userData.email, email, dias: parseInt(dias)})});
            carregarAdmin();
            alert('Ativado!');
        }

        async function adminDesativar() {
            const email = document.getElementById('adminEmail').value;
            if (!email) return alert('Digite o email!');
            await fetch('/api/admin/desativar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({admin_email: userData.email, email})});
            carregarAdmin();
            alert('Desativado!');
        }

        setInterval(carregarDados, 5000);
    </script>
</body>
</html>
"""

# ═══════════════════════════════════════════
# ROTAS DO SITE
# ═══════════════════════════════════════════

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/manifest.json')
def manifest():
    return {"name":"Quantum IA","short_name":"QuantumIA","start_url":"/","display":"standalone","background_color":"#0a0a0a","theme_color":"#6c00ff"}

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    u = get_user_by_email(data['email'])
    if u and u['senha'] == data['senha']:
        if not user_ativo(data['email']):
            return jsonify({"status":"erro","msg":"Acesso expirado!"}), 403
        return jsonify({"status":"ok","user":{"id":u['id'],"email":u['email'],"nome":u['nome'],"admin":bool(u['admin']),"expiracao":u.get('expiracao','')}})
    return jsonify({"status":"erro","msg":"Email ou senha inválidos!"}), 401

@app.route('/api/status', methods=['POST'])
def api_status():
    data = request.json
    u = get_user_by_email(data['email'])
    if not u: return jsonify({"status":"erro"}), 404
    res = resultado_dia(u['id'])
    return jsonify({"bot_ligado":bool(u.get('bot_ligado',0)),"saldo":u.get('saldo',0),"hoje":res,"config":{"iq_email":u.get('iq_email',''),"iq_conta":u.get('iq_conta','PRACTICE'),"valor_entrada":u.get('valor_entrada',2.0),"multiplicador":u.get('multiplicador',2.0),"max_gales":u.get('max_gales',1),"stop_loss":u.get('stop_loss',0),"stop_win":u.get('stop_win',0)}})

@app.route('/api/config', methods=['POST'])
def api_config():
    data = request.json
    email = data.pop('email', None)
    if not email: return jsonify({"status":"erro"}), 400
    conn = sqlite3.connect(DB_PATH)
    sets = ", ".join(f"{k}=?" for k in data)
    vals = list(data.values()) + [email]
    conn.execute(f"UPDATE users SET {sets} WHERE email=?", vals)
    conn.commit()
    conn.close()
    return jsonify({"status":"ok"})

@app.route('/api/ligar', methods=['POST'])
def api_ligar():
    email = request.json['email']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET bot_ligado=1 WHERE email=?", (email,))
    conn.commit()
    conn.close()
    return jsonify({"status":"ok"})

@app.route('/api/desligar', methods=['POST'])
def api_desligar():
    email = request.json['email']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET bot_ligado=0 WHERE email=?", (email,))
    conn.commit()
    conn.close()
    return jsonify({"status":"ok"})

@app.route('/api/historico', methods=['POST'])
def api_historico():
    u = get_user_by_email(request.json['email'])
    if not u: return jsonify([])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, ativo, direcao, valor, resultado, lucro FROM trades WHERE user_id=? ORDER BY id DESC LIMIT 50", (u['id'],))
    rows = [{"data":r[0],"ativo":r[1],"direcao":r[2],"valor":r[3],"resultado":r[4],"lucro":r[5]} for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/admin/usuarios', methods=['POST'])
def api_admin_usuarios():
    u = get_user_by_email(request.json['email'])
    if not u or not u['admin']: return jsonify({"status":"erro"}), 403
    return jsonify(listar_users())

@app.route('/api/admin/ativar', methods=['POST'])
def api_admin_ativar():
    admin = get_user_by_email(request.json['admin_email'])
    if not admin or not admin['admin']: return jsonify({"status":"erro"}), 403
    email = request.json['email']
    dias = int(request.json.get('dias', 30))
    u = get_user_by_email(email)
    if u:
        ativar_user(email, dias)
    else:
        criar_usuario(email, email.split('@')[0], dias)
    return jsonify({"status":"ok"})

@app.route('/api/admin/desativar', methods=['POST'])
def api_admin_desativar():
    admin = get_user_by_email(request.json['admin_email'])
    if not admin or not admin['admin']: return jsonify({"status":"erro"}), 403
    desativar_user(request.json['email'])
    return jsonify({"status":"ok"})

# ═══════════════════════════════════════════
# INICIAR
# ═══════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    threading.Thread(target=trading_loop, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
