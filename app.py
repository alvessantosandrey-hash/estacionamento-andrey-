from flask import Flask, render_template_string, request, redirect, url_for, flash
from datetime import datetime, timedelta
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "estacionamento_secreto_123"

DB = "estacionamento.db"

# ====================== BANCO DE DADOS ======================
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Clientes
    c.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            telefone TEXT,
            email TEXT,
            cpf TEXT UNIQUE,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Veículos
    c.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            placa TEXT UNIQUE NOT NULL,
            modelo TEXT,
            cor TEXT,
            cliente_id INTEGER,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )
    """)

    # Vagas
    c.execute("""
        CREATE TABLE IF NOT EXISTS vagas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT UNIQUE NOT NULL,
            tipo TEXT DEFAULT 'comum',  -- comum, preferencial, moto
            status TEXT DEFAULT 'livre' -- livre, ocupada, reservada
        )
    """)

    # Preços
    c.execute("""
        CREATE TABLE IF NOT EXISTS precos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor_hora REAL DEFAULT 0,
            valor_diaria REAL DEFAULT 0,
            valor_mensal REAL DEFAULT 0,
            ativo INTEGER DEFAULT 1
        )
    """)

    # Movimentações (entrada/saída)
    c.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            vaga_id INTEGER NOT NULL,
            entrada TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            saida TIMESTAMP,
            valor_pago REAL DEFAULT 0,
            forma_pagamento TEXT,
            status TEXT DEFAULT 'ativo', -- ativo, finalizado
            FOREIGN KEY (veiculo_id) REFERENCES veiculos(id),
            FOREIGN KEY (vaga_id) REFERENCES vagas(id)
        )
    """)

    # Inserir preços padrão se não existirem
    c.execute("SELECT COUNT(*) FROM precos")
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO precos (descricao, valor_hora, valor_diaria, valor_mensal)
            VALUES ('Tabela Padrão', 8.00, 40.00, 350.00)
        """)

    # Criar algumas vagas se não existirem
    c.execute("SELECT COUNT(*) FROM vagas")
    if c.fetchone()[0] == 0:
        for i in range(1, 21):
            tipo = "preferencial" if i <= 3 else "moto" if i > 17 else "comum"
            c.execute("INSERT INTO vagas (numero, tipo) VALUES (?, ?)", (f"V{i:02d}", tipo))

    conn.commit()
    conn.close()

# ====================== FUNÇÕES AUXILIARES ======================
def calcular_valor(entrada, saida=None):
    if not saida:
        saida = datetime.now()
    else:
        saida = datetime.fromisoformat(saida) if isinstance(saida, str) else saida

    entrada = datetime.fromisoformat(entrada) if isinstance(entrada, str) else entrada
    tempo = saida - entrada
    horas = tempo.total_seconds() / 3600

    conn = get_db()
    preco = conn.execute("SELECT * FROM precos WHERE ativo = 1 LIMIT 1").fetchone()
    conn.close()

    if not preco:
        return 0

    if horas <= 1:
        return preco["valor_hora"]
    elif horas <= 24:
        return preco["valor_hora"] * horas
    else:
        diarias = int(horas // 24)
        resto_horas = horas % 24
        return (diarias * preco["valor_diaria"]) + (resto_horas * preco["valor_hora"])

# ====================== ROTAS ======================
@app.route("/")
def index():
    conn = get_db()
    vagas = conn.execute("SELECT * FROM vagas ORDER BY numero").fetchall()
    ocupadas = conn.execute("SELECT COUNT(*) FROM vagas WHERE status = 'ocupada'").fetchone()[0]
    livres = conn.execute("SELECT COUNT(*) FROM vagas WHERE status = 'livre'").fetchone()[0]
    ativos = conn.execute("""
        SELECT m.*, v.placa, v.modelo, vg.numero as vaga_numero
        FROM movimentacoes m
        JOIN veiculos v ON m.veiculo_id = v.id
        JOIN vagas vg ON m.vaga_id = vg.id
        WHERE m.status = 'ativo'
        ORDER BY m.entrada DESC
    """).fetchall()
    conn.close()

    return render_template_string(TEMPLATE_INDEX, 
                                  vagas=vagas, 
                                  ocupadas=ocupadas, 
                                  livres=livres, 
                                  ativos=ativos)

@app.route("/clientes")
def clientes():
    conn = get_db()
    clientes = conn.execute("SELECT * FROM clientes ORDER BY nome").fetchall()
    conn.close()
    return render_template_string(TEMPLATE_CLIENTES, clientes=clientes)

@app.route("/clientes/novo", methods=["GET", "POST"])
def novo_cliente():
    if request.method == "POST":
        nome = request.form["nome"]
        telefone = request.form.get("telefone")
        email = request.form.get("email")
        cpf = request.form.get("cpf")
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO clientes (nome, telefone, email, cpf) VALUES (?, ?, ?, ?)",
                (nome, telefone, email, cpf)
            )
            conn.commit()
            flash("Cliente cadastrado com sucesso!", "success")
        except sqlite3.IntegrityError:
            flash("CPF já cadastrado!", "danger")
        conn.close()
        return redirect(url_for("clientes"))
    return render_template_string(TEMPLATE_NOVO_CLIENTE)

@app.route("/veiculos")
def veiculos():
    conn = get_db()
    veiculos = conn.execute("""
        SELECT v.*, c.nome as cliente_nome 
        FROM veiculos v 
        LEFT JOIN clientes c ON v.cliente_id = c.id
        ORDER BY v.placa
    """).fetchall()
    clientes = conn.execute("SELECT id, nome FROM clientes ORDER BY nome").fetchall()
    conn.close()
    return render_template_string(TEMPLATE_VEICULOS, veiculos=veiculos, clientes=clientes)

@app.route("/veiculos/novo", methods=["POST"])
def novo_veiculo():
    placa = request.form["placa"].upper().replace(" ", "").replace("-", "")
    modelo = request.form.get("modelo")
    cor = request.form.get("cor")
    cliente_id = request.form.get("cliente_id") or None

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO veiculos (placa, modelo, cor, cliente_id) VALUES (?, ?, ?, ?)",
            (placa, modelo, cor, cliente_id)
        )
        conn.commit()
        flash("Veículo cadastrado!", "success")
    except sqlite3.IntegrityError:
        flash("Placa já cadastrada!", "danger")
    conn.close()
    return redirect(url_for("veiculos"))

@app.route("/entrada", methods=["GET", "POST"])
def entrada():
    conn = get_db()
    if request.method == "POST":
        placa = request.form["placa"].upper().replace(" ", "").replace("-", "")
        vaga_id = request.form["vaga_id"]

        veiculo = conn.execute("SELECT * FROM veiculos WHERE placa = ?", (placa,)).fetchone()
        if not veiculo:
            # Cria veículo rápido se não existir
            conn.execute("INSERT INTO veiculos (placa) VALUES (?)", (placa,))
            veiculo = conn.execute("SELECT * FROM veiculos WHERE placa = ?", (placa,)).fetchone()

        # Verifica se já está dentro
        ativo = conn.execute(
            "SELECT * FROM movimentacoes WHERE veiculo_id = ? AND status = 'ativo'",
            (veiculo["id"],)
        ).fetchone()
        if ativo:
            flash("Este veículo já está no estacionamento!", "warning")
            conn.close()
            return redirect(url_for("entrada"))

        # Atualiza vaga e cria movimentação
        conn.execute("UPDATE vagas SET status = 'ocupada' WHERE id = ?", (vaga_id,))
        conn.execute(
            "INSERT INTO movimentacoes (veiculo_id, vaga_id) VALUES (?, ?)",
            (veiculo["id"], vaga_id)
        )
        conn.commit()
        flash(f"Entrada registrada! Placa {placa}", "success")
        conn.close()
        return redirect(url_for("index"))

    vagas_livres = conn.execute("SELECT * FROM vagas WHERE status = 'livre' ORDER BY numero").fetchall()
    conn.close()
    return render_template_string(TEMPLATE_ENTRADA, vagas=vagas_livres)

@app.route("/saida/<int:mov_id>", methods=["GET", "POST"])
def saida(mov_id):
    conn = get_db()
    mov = conn.execute("""
        SELECT m.*, v.placa, v.modelo, vg.numero as vaga_numero
        FROM movimentacoes m
        JOIN veiculos v ON m.veiculo_id = v.id
        JOIN vagas vg ON m.vaga_id = vg.id
        WHERE m.id = ?
    """, (mov_id,)).fetchone()

    if not mov or mov["status"] != "ativo":
        flash("Movimentação não encontrada ou já finalizada.", "danger")
        conn.close()
        return redirect(url_for("index"))

    valor = calcular_valor(mov["entrada"])

    if request.method == "POST":
        forma = request.form.get("forma_pagamento", "dinheiro")
        saida_agora = datetime.now().isoformat()

        conn.execute("""
            UPDATE movimentacoes 
            SET saida = ?, valor_pago = ?, forma_pagamento = ?, status = 'finalizado'
            WHERE id = ?
        """, (saida_agora, valor, forma, mov_id))

        conn.execute("UPDATE vagas SET status = 'livre' WHERE id = ?", (mov["vaga_id"],))
        conn.commit()
        flash(f"Saída registrada! Valor: R$ {valor:.2f}", "success")
        conn.close()
        return redirect(url_for("index"))

    conn.close()
    return render_template_string(TEMPLATE_SAIDA, mov=mov, valor=valor)

@app.route("/precos")
def precos():
    conn = get_db()
    precos = conn.execute("SELECT * FROM precos").fetchall()
    conn.close()
    return render_template_string(TEMPLATE_PRECOS, precos=precos)

@app.route("/precos/editar", methods=["POST"])
def editar_preco():
    conn = get_db()
    conn.execute("""
        UPDATE precos SET 
            valor_hora = ?, 
            valor_diaria = ?, 
            valor_mensal = ?
        WHERE id = ?
    """, (
        float(request.form["valor_hora"]),
        float(request.form["valor_diaria"]),
        float(request.form["valor_mensal"]),
        request.form["id"]
    ))
    conn.commit()
    conn.close()
    flash("Preços atualizados!", "success")
    return redirect(url_for("precos"))

# ====================== TEMPLATES ======================
BASE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistema de Estacionamento</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #f0f2f5; }
        .vaga { width: 70px; height: 90px; border-radius: 8px; display: flex; flex-direction: column; align-items: center; justify-content: center; font-weight: bold; margin: 5px; }
        .livre { background: #28a745; color: white; }
        .ocupada { background: #dc3545; color: white; }
        .preferencial { border: 3px solid #ffc107; }
        .moto { background: #17a2b8; }
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
    <div class="container">
        <a class="navbar-brand" href="/">🅿️ Estacionamento</a>
        <div class="navbar-nav">
            <a class="nav-link" href="/">Dashboard</a>
            <a class="nav-link" href="/entrada">Entrada</a>
            <a class="nav-link" href="/clientes">Clientes</a>
            <a class="nav-link" href="/veiculos">Veículos</a>
            <a class="nav-link" href="/precos">Preços</a>
        </div>
    </div>
</nav>
<div class="container">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }} alert-dismissible fade show">{{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    {{ content|safe }}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

TEMPLATE_INDEX = BASE.replace("{{ content|safe }}", """
<div class="row mb-4">
    <div class="col-md-4">
        <div class="card text-center">
            <div class="card-body">
                <h5>Vagas Livres</h5>
                <h2 class="text-success">{{ livres }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card text-center">
            <div class="card-body">
                <h5>Vagas Ocupadas</h5>
                <h2 class="text-danger">{{ ocupadas }}</h2>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card text-center">
            <div class="card-body">
                <h5>Total de Vagas</h5>
                <h2>{{ livres + ocupadas }}</h2>
            </div>
        </div>
    </div>
</div>

<div class="card mb-4">
    <div class="card-header"><strong>Mapa de Vagas</strong></div>
    <div class="card-body d-flex flex-wrap">
        {% for v in vagas %}
            <div class="vaga {{ v.status }} {% if v.tipo == 'preferencial' %}preferencial{% endif %} {% if v.tipo == 'moto' %}moto{% endif %}">
                <div>{{ v.numero }}</div>
                <small>{{ v.tipo }}</small>
            </div>
        {% endfor %}
    </div>
</div>

<div class="card">
    <div class="card-header d-flex justify-content-between">
        <strong>Veículos no Estacionamento</strong>
        <a href="/entrada" class="btn btn-sm btn-success">+ Nova Entrada</a>
    </div>
    <div class="card-body">
        <table class="table table-hover">
            <thead>
                <tr>
                    <th>Placa</th>
                    <th>Modelo</th>
                    <th>Vaga</th>
                    <th>Entrada</th>
                    <th>Ação</th>
                </tr>
            </thead>
            <tbody>
                {% for a in ativos %}
                <tr>
                    <td><strong>{{ a.placa }}</strong></td>
                    <td>{{ a.modelo or '-' }}</td>
                    <td>{{ a.vaga_numero }}</td>
                    <td>{{ a.entrada[:16].replace('T', ' ') }}</td>
                    <td>
                        <a href="/saida/{{ a.id }}" class="btn btn-sm btn-warning">Registrar Saída</a>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="5" class="text-center text-muted">Nenhum veículo no momento</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
""")

TEMPLATE_CLIENTES = BASE.replace("{{ content|safe }}", """
<div class="d-flex justify-content-between mb-3">
    <h3>Clientes</h3>
    <a href="/clientes/novo" class="btn btn-primary">+ Novo Cliente</a>
</div>
<table class="table table-striped">
    <thead>
        <tr>
            <th>Nome</th>
            <th>Telefone</th>
            <th>Email</th>
            <th>CPF</th>
        </tr>
    </thead>
    <tbody>
        {% for c in clientes %}
        <tr>
            <td>{{ c.nome }}</td>
            <td>{{ c.telefone or '-' }}</td>
            <td>{{ c.email or '-' }}</td>
            <td>{{ c.cpf or '-' }}</td>
        </tr>
        {% else %}
        <tr><td colspan="4" class="text-center">Nenhum cliente cadastrado</td></tr>
        {% endfor %}
    </tbody>
</table>
""")

TEMPLATE_NOVO_CLIENTE = BASE.replace("{{ content|safe }}", """
<h3>Novo Cliente</h3>
<form method="POST" class="card p-4">
    <div class="mb-3">
        <label class="form-label">Nome *</label>
        <input type="text" name="nome" class="form-control" required>
    </div>
    <div class="mb-3">
        <label class="form-label">Telefone</label>
        <input type="text" name="telefone" class="form-control">
    </div>
    <div class="mb-3">
        <label class="form-label">Email</label>
        <input type="email" name="email" class="form-control">
    </div>
    <div class="mb-3">
        <label class="form-label">CPF</label>
        <input type="text" name="cpf" class="form-control">
    </div>
    <button type="submit" class="btn btn-success">Salvar</button>
    <a href="/clientes" class="btn btn-secondary">Cancelar</a>
</form>
""")

TEMPLATE_VEICULOS = BASE.replace("{{ content|safe }}", """
<div class="row">
    <div class="col-md-8">
        <h3>Veículos</h3>
        <table class="table table-striped">
            <thead>
                <tr>
                    <th>Placa</th>
                    <th>Modelo</th>
                    <th>Cor</th>
                    <th>Cliente</th>
                </tr>
            </thead>
            <tbody>
                {% for v in veiculos %}
                <tr>
                    <td><strong>{{ v.placa }}</strong></td>
                    <td>{{ v.modelo or '-' }}</td>
                    <td>{{ v.cor or '-' }}</td>
                    <td>{{ v.cliente_nome or 'Avulso' }}</td>
                </tr>
                {% else %}
                <tr><td colspan="4" class="text-center">Nenhum veículo</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <div class="col-md-4">
        <div class="card">
            <div class="card-header">Cadastrar Veículo</div>
            <div class="card-body">
                <form method="POST" action="/veiculos/novo">
                    <div class="mb-2">
                        <label class="form-label">Placa *</label>
                        <input type="text" name="placa" class="form-control" required placeholder="ABC1D23">
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Modelo</label>
                        <input type="text" name="modelo" class="form-control">
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Cor</label>
                        <input type="text" name="cor" class="form-control">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Cliente</label>
                        <select name="cliente_id" class="form-select">
                            <option value="">Avulso</option>
                            {% for c in clientes %}
                            <option value="{{ c.id }}">{{ c.nome }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Cadastrar</button>
                </form>
            </div>
        </div>
    </div>
</div>
""")

TEMPLATE_ENTRADA = BASE.replace("{{ content|safe }}", """
<h3>Registrar Entrada</h3>
<form method="POST" class="card p-4" style="max-width: 500px;">
    <div class="mb-3">
        <label class="form-label">Placa do Veículo *</label>
        <input type="text" name="placa" class="form-control form-control-lg" required placeholder="ABC1D23" autofocus>
    </div>
    <div class="mb-3">
        <label class="form-label">Vaga *</label>
        <select name="vaga_id" class="form-select" required>
            <option value="">Selecione a vaga...</option>
            {% for v in vagas %}
            <option value="{{ v.id }}">{{ v.numero }} ({{ v.tipo }})</option>
            {% endfor %}
        </select>
    </div>
    <button type="submit" class="btn btn-success btn-lg">Registrar Entrada</button>
</form>
""")

TEMPLATE_SAIDA = BASE.replace("{{ content|safe }}", """
<div class="card" style="max-width: 500px;">
    <div class="card-header bg-warning">
        <h4 class="mb-0">Registrar Saída</h4>
    </div>
    <div class="card-body">
        <p><strong>Placa:</strong> {{ mov.placa }}</p>
        <p><strong>Modelo:</strong> {{ mov.modelo or '-' }}</p>
        <p><strong>Vaga:</strong> {{ mov.vaga_numero }}</p>
        <p><strong>Entrada:</strong> {{ mov.entrada[:16].replace('T', ' ') }}</p>
        <hr>
        <h3 class="text-center text-success">R$ {{ "%.2f"|format(valor) }}</h3>
        <form method="POST">
            <div class="mb-3">
                <label class="form-label">Forma de Pagamento</label>
                <select name="forma_pagamento" class="form-select">
                    <option value="dinheiro">Dinheiro</option>
                    <option value="pix">PIX</option>
                    <option value="cartao">Cartão</option>
                </select>
            </div>
            <button type="submit" class="btn btn-success w-100 btn-lg">Confirmar Saída e Pagamento</button>
        </form>
    </div>
</div>
""")

TEMPLATE_PRECOS = BASE.replace("{{ content|safe }}", """
<h3>Tabela de Preços</h3>
{% for p in precos %}
<form method="POST" action="/precos/editar" class="card p-4 mb-3">
    <input type="hidden" name="id" value="{{ p.id }}">
    <div class="row">
        <div class="col-md-3">
            <label class="form-label">Valor Hora (R$)</label>
            <input type="number" step="0.01" name="valor_hora" class="form-control" value="{{ p.valor_hora }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">Valor Diária (R$)</label>
            <input type="number" step="0.01" name="valor_diaria" class="form-control" value="{{ p.valor_diaria }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">Valor Mensal (R$)</label>
            <input type="number" step="0.01" name="valor_mensal" class="form-control" value="{{ p.valor_mensal }}">
        </div>
        <div class="col-md-3 d-flex align-items-end">
            <button type="submit" class="btn btn-primary w-100">Salvar</button>
        </div>
    </div>
</form>
{% endfor %}
""")

# ====================== INICIALIZAÇÃO ======================
if __name__ == "__main__":
    init_db()
    print("✅ Banco de dados criado/verificado!")
    print("🚀 Sistema rodando em http://127.0.0.1:5000")
    app.run(debug=True, port=5000)