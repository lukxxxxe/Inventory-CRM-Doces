from flask import Flask, render_template, request, redirect, flash, jsonify
import sqlite3
from datetime import date

app = Flask(__name__)
app.secret_key = 'supersegredo'

# ============================================================
# BANCO DE DADOS
# ============================================================

def inicializar_banco():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    # Estoque de insumos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            quantidade REAL NOT NULL,
            custo_unit REAL NOT NULL,
            custo_total REAL DEFAULT 0,
            data_entrada TEXT NOT NULL
        )
    ''')

    # Produtos conhecidos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        )
    ''')

    # Produtos acabados
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS acabados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            quantidade REAL NOT NULL,
            custo_unit REAL DEFAULT 0,
            custo_total REAL DEFAULT 0,
            preco_venda REAL DEFAULT 0,
            data TEXT NOT NULL
        )
    ''')

    # Receitas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS receitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto TEXT NOT NULL,
            insumo TEXT NOT NULL,
            quantidade REAL NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


def atualizar_colunas_novas():
    """Garante que as novas colunas existam em bancos antigos."""
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    colunas_estoque = [c[1] for c in cursor.execute("PRAGMA table_info(estoque)")]
    if "custo_total" not in colunas_estoque:
        cursor.execute("ALTER TABLE estoque ADD COLUMN custo_total REAL DEFAULT 0")

    colunas_acabados = [c[1] for c in cursor.execute("PRAGMA table_info(acabados)")]
    for nova_col in ["custo_unit", "custo_total", "preco_venda"]:
        if nova_col not in colunas_acabados:
            cursor.execute(f"ALTER TABLE acabados ADD COLUMN {nova_col} REAL DEFAULT 0")

    conn.commit()
    conn.close()

# ============================================================
# FUNÇÕES DE ESTOQUE
# ============================================================

def inserir_produto_estoque(nome, quantidade, custo_unit, data_entrada, eh_total=True):
    """Insere insumo no estoque, com custo total calculado."""
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    cursor.execute('SELECT id FROM produtos WHERE nome=?', (nome,))
    if not cursor.fetchone():
        cursor.execute('INSERT INTO produtos (nome) VALUES (?)', (nome,))

    try:
        quantidade = float(quantidade)
        custo_informado = float(custo_unit)
        if quantidade > 0:
            if eh_total:
                custo_unit_corrigido = round(custo_informado / quantidade, 6)
                custo_total = custo_informado
            else:
                custo_unit_corrigido = round(custo_informado, 6)
                custo_total = round(custo_informado * quantidade, 2)
        else:
            custo_unit_corrigido = 0
            custo_total = 0
    except Exception:
        custo_unit_corrigido = 0
        custo_total = 0

    cursor.execute('''
        INSERT INTO estoque (nome, quantidade, custo_unit, custo_total, data_entrada)
        VALUES (?, ?, ?, ?, ?)
    ''', (nome, quantidade, custo_unit_corrigido, custo_total, data_entrada))

    conn.commit()
    conn.close()


def consultar_estoque(filtro_nome=None):
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    if filtro_nome:
        cursor.execute('''
            SELECT id, nome, quantidade, custo_unit, custo_total, data_entrada
            FROM estoque WHERE nome LIKE ? ORDER BY date(data_entrada) ASC
        ''', (f'%{filtro_nome}%',))
    else:
        cursor.execute('SELECT id, nome, quantidade, custo_unit, custo_total, data_entrada FROM estoque ORDER BY date(data_entrada) ASC')
    dados = cursor.fetchall()
    conn.close()
    return dados


def listar_produtos():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT nome FROM produtos ORDER BY nome ASC')
    nomes = [r[0] for r in cursor.fetchall()]
    conn.close()
    return nomes

# ============================================================
# RECEITAS / PRODUÇÃO
# ============================================================

def listar_receitas():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT produto FROM receitas ORDER BY produto ASC')
    nomes = [r[0] for r in cursor.fetchall()]
    conn.close()
    return nomes


def consultar_acabados():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, nome, quantidade, custo_unit, custo_total, preco_venda, data FROM acabados ORDER BY date(data) ASC')
    dados = cursor.fetchall()
    conn.close()
    return dados


def verificar_insumos_disponiveis(produto, qtd):
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT insumo, quantidade FROM receitas WHERE LOWER(produto)=LOWER(?)', (produto,))
    insumos = cursor.fetchall()

    faltantes = []
    for insumo, qtd_rec in insumos:
        cursor.execute('SELECT SUM(quantidade) FROM estoque WHERE nome=?', (insumo,))
        total_disp = cursor.fetchone()[0] or 0
        if total_disp < qtd_rec * qtd:
            faltantes.append((insumo, round(qtd_rec * qtd - total_disp, 2)))
    conn.close()
    return faltantes


def consumir_insumo_fifo(conn, insumo, qtd_necessaria):
    cursor = conn.cursor()
    cursor.execute('SELECT id, quantidade FROM estoque WHERE nome=? ORDER BY date(data_entrada) ASC', (insumo,))
    lotes = cursor.fetchall()

    restante = qtd_necessaria
    for lote_id, qtd_em_lote in lotes:
        if restante <= 0:
            break
        if qtd_em_lote <= restante:
            cursor.execute('DELETE FROM estoque WHERE id=?', (lote_id,))
            restante -= qtd_em_lote
        else:
            cursor.execute('UPDATE estoque SET quantidade=quantidade-? WHERE id=?', (restante, lote_id))
            restante = 0


def registrar_producao(produto, qtd, preco_venda):
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    data_hoje = date.today().isoformat()

    faltantes = verificar_insumos_disponiveis(produto, qtd)
    if faltantes:
        conn.close()
        return faltantes

    # Cálculo de custo total e unitário
    cursor.execute('SELECT insumo, quantidade FROM receitas WHERE LOWER(produto)=LOWER(?)', (produto,))
    insumos = cursor.fetchall()

    custo_total = 0
    for insumo, qtd_insumo in insumos:
        qtd_total = qtd_insumo * qtd
        cursor.execute('SELECT quantidade, custo_unit FROM estoque WHERE nome=? ORDER BY date(data_entrada) ASC', (insumo,))
        lotes = cursor.fetchall()
        restante = qtd_total
        for q_lote, c_unit in lotes:
            if restante <= 0:
                break
            usado = min(q_lote, restante)
            custo_total += usado * c_unit
            restante -= usado
        consumir_insumo_fifo(conn, insumo, qtd_total)

    custo_unit = round(custo_total / qtd, 6) if qtd else 0
    cursor.execute('''
        INSERT INTO acabados (nome, quantidade, custo_unit, custo_total, preco_venda, data)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (produto, qtd, custo_unit, custo_total, preco_venda, data_hoje))

    conn.commit()
    conn.close()
    return []


# ============================================================
# ROTAS
# ============================================================

@app.route('/')
def index():
    filtro = request.args.get('filtro')
    insumos = consultar_estoque(filtro)
    conhecidos = listar_produtos()
    receitas_conhecidas = listar_receitas()
    acabados = consultar_acabados()
    data_hoje = date.today().isoformat()
    return render_template('index.html', produtos=insumos, conhecidos=conhecidos,
                           receitas_conhecidas=receitas_conhecidas, acabados=acabados,
                           data_hoje=data_hoje, filtro=filtro or "")


@app.route('/add', methods=['POST'])
def add():
    nome = request.form['nome']
    qtd = float(request.form['quantidade'])
    custo = float(request.form['custo'])
    data_entrada = request.form['data']
    eh_total = 'eh_total' in request.form
    inserir_produto_estoque(nome, qtd, custo, data_entrada, eh_total)
    return redirect('/')


@app.route('/produzir', methods=['POST'])
def produzir():
    produto = request.form['produto']
    qtd = float(request.form['quantidade'])
    preco_venda = float(request.form['preco_venda'])
    faltantes = registrar_producao(produto, qtd, preco_venda)
    if faltantes:
        flash("❌ Faltam insumos: " + ", ".join([f"{qtd} de {nome}" for nome, qtd in faltantes]))
    else:
        flash(f"✅ {qtd}x {produto} produzido!")
    return redirect('/')


@app.route('/editar_venda/<int:id>', methods=['POST'])
def editar_venda(id):
    novo_preco = float(request.form['preco_venda'])
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE acabados SET preco_venda=? WHERE id=?', (novo_preco, id))
    conn.commit()
    conn.close()
    flash("💰 Preço atualizado com sucesso!")
    return redirect('/')


@app.route('/custo/<path:produto>/<quantidade>')
def custo(produto, quantidade):
    qtd = float(quantidade)
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT insumo, quantidade FROM receitas WHERE LOWER(produto)=LOWER(?)', (produto,))
    insumos = cursor.fetchall()

    custo_total = 0
    for insumo, qtd_i in insumos:
        qtd_total = qtd_i * qtd
        cursor.execute('SELECT quantidade, custo_unit FROM estoque WHERE nome=? ORDER BY date(data_entrada) ASC', (insumo,))
        lotes = cursor.fetchall()
        restante = qtd_total
        for q_lote, c_unit in lotes:
            if restante <= 0:
                break
            usado = min(q_lote, restante)
            custo_total += usado * c_unit
            restante -= usado

    conn.close()
    custo_unit = round(custo_total / qtd, 6) if qtd else 0
    sugerido = round(custo_total / 0.7, 2) if custo_total > 0 else 0
    return jsonify({"unitario": custo_unit, "total": round(custo_total, 2), "sugerido": sugerido})


@app.route('/receitas')
def receitas():
    produto_filtro = request.args.get('produto', '').strip()
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    if produto_filtro:
        cursor.execute('SELECT produto, insumo, quantidade, id FROM receitas WHERE produto LIKE ? ORDER BY produto ASC', (f'%{produto_filtro}%',))
    else:
        cursor.execute('SELECT produto, insumo, quantidade, id FROM receitas ORDER BY produto ASC')
    dados = cursor.fetchall()

    cursor.execute('SELECT DISTINCT produto FROM receitas ORDER BY produto ASC')
    produtos = [r[0] for r in cursor.fetchall()]

    cursor.execute('SELECT nome FROM produtos ORDER BY nome ASC')
    insumos = [r[0] for r in cursor.fetchall()]

    conn.close()
    return render_template('receitas.html', receitas=dados, produtos=produtos, insumos=insumos, produto_filtro=produto_filtro)


@app.route('/add_receita', methods=['POST'])
def add_receita():
    produto = request.form['produto']
    insumo = request.form['insumo']
    qtd = float(request.form['quantidade'])
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO receitas (produto, insumo, quantidade) VALUES (?, ?, ?)', (produto, insumo, qtd))
    conn.commit()
    conn.close()
    return redirect('/receitas')

@app.route('/delete_insumo/<int:id>')
def delete_insumo(id):
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM estoque WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/delete_receita/<int:id>')
def delete_receita(id):
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM receitas WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect('/receitas')

# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == '__main__':
    inicializar_banco()
    atualizar_colunas_novas()
    app.run(debug=True)
