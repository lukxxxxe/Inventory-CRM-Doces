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

# ============================================================
# FUNÇÕES DE ESTOQUE
# ============================================================

def inserir_produto_estoque(nome, quantidade, custo_unit, data_entrada, eh_total=True):
    """Insere insumo no estoque.
    Se 'eh_total' for True, interpreta o custo informado como custo total do lote.
    Caso contrário, considera o valor informado como custo unitário direto.
    """
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    # Garante que o insumo esteja cadastrado
    cursor.execute('SELECT id FROM produtos WHERE nome = ?', (nome,))
    existe = cursor.fetchone()
    if not existe:
        cursor.execute('INSERT INTO produtos (nome) VALUES (?)', (nome,))

    try:
        quantidade_float = float(quantidade)
        custo_informado = float(custo_unit)
        if quantidade_float > 0:
            if eh_total:
                custo_unitario_corrigido = round(custo_informado / quantidade_float, 6)
            else:
                custo_unitario_corrigido = round(custo_informado, 6)
        else:
            custo_unitario_corrigido = 0
    except Exception:
        custo_unitario_corrigido = 0

    cursor.execute('''
        INSERT INTO estoque (nome, quantidade, custo_unit, data_entrada)
        VALUES (?, ?, ?, ?)
    ''', (nome, quantidade_float, custo_unitario_corrigido, data_entrada))

    conn.commit()
    conn.close()


def consultar_estoque():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT nome, quantidade, custo_unit, data_entrada FROM estoque ORDER BY date(data_entrada) ASC')
    dados = cursor.fetchall()
    conn.close()
    return dados


def listar_produtos():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT nome FROM produtos ORDER BY nome ASC')
    nomes = [row[0] for row in cursor.fetchall()]
    conn.close()
    return nomes

# ============================================================
# FUNÇÕES DE RECEITAS / PRODUÇÃO
# ============================================================

def listar_receitas():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT produto FROM receitas ORDER BY produto ASC')
    nomes = [row[0] for row in cursor.fetchall()]
    conn.close()
    return nomes


def consultar_acabados():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT nome, quantidade, data FROM acabados ORDER BY date(data) ASC')
    dados = cursor.fetchall()
    conn.close()
    return dados


def verificar_insumos_disponiveis(produto, quantidade_produzir):
    """Verifica se há insumos suficientes para produzir."""
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('SELECT insumo, quantidade FROM receitas WHERE LOWER(produto)=LOWER(?)', (produto,))
    insumos = cursor.fetchall()

    faltantes = []
    for insumo, qtd_necessaria in insumos:
        cursor.execute('SELECT SUM(quantidade) FROM estoque WHERE nome = ?', (insumo,))
        total_disp = cursor.fetchone()[0] or 0
        total_nec = qtd_necessaria * quantidade_produzir

        if total_disp < total_nec:
            faltantes.append((insumo, round(total_nec - total_disp, 2)))

    conn.close()
    return faltantes


def consumir_insumo_fifo(conn, insumo, quantidade_necessaria):
    """Baixa estoque pelo método FIFO."""
    cursor = conn.cursor()
    cursor.execute('SELECT id, quantidade FROM estoque WHERE nome=? ORDER BY date(data_entrada) ASC', (insumo,))
    lotes = cursor.fetchall()

    restante = quantidade_necessaria
    for lote_id, qtd_em_lote in lotes:
        if restante <= 0:
            break

        if qtd_em_lote <= restante:
            cursor.execute('DELETE FROM estoque WHERE id=?', (lote_id,))
            restante -= qtd_em_lote
        else:
            cursor.execute('UPDATE estoque SET quantidade = quantidade - ? WHERE id=?', (restante, lote_id))
            restante = 0


def registrar_producao(produto, qtd):
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    data_hoje = date.today().isoformat()

    # Verifica estoque suficiente antes
    faltantes = verificar_insumos_disponiveis(produto, qtd)
    if faltantes:
        conn.close()
        return faltantes

    # Adiciona produto acabado
    cursor.execute('INSERT INTO acabados (nome, quantidade, data) VALUES (?, ?, ?)', (produto, qtd, data_hoje))

    # Busca receita e consome insumos FIFO
    cursor.execute('SELECT insumo, quantidade FROM receitas WHERE LOWER(produto)=LOWER(?)', (produto,))
    insumos = cursor.fetchall()
    for insumo, qtd_necessaria in insumos:
        consumir_insumo_fifo(conn, insumo, qtd_necessaria * qtd)

    conn.commit()
    conn.close()
    return []

# ============================================================
# CÁLCULO DE CUSTO
# ============================================================

@app.route('/custo/<path:produto>/<quantidade>')
def calcular_custo(produto, quantidade):
    """Calcula custo total e sugerido da produção."""
    print(f"[DEBUG] ROTA CUSTO - Produto: {produto}, Qtd: {quantidade}")
    qtd = float(quantidade)
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    cursor.execute('SELECT insumo, quantidade FROM receitas WHERE LOWER(produto)=LOWER(?)', (produto,))
    insumos = cursor.fetchall()
    print(f"[DEBUG] Insumos encontrados: {insumos}")

    custo_total = 0.0

    for insumo, qtd_necessaria in insumos:
        qtd_total_necessaria = qtd_necessaria * qtd

        cursor.execute('SELECT quantidade, custo_unit FROM estoque WHERE nome=? ORDER BY date(data_entrada) ASC', (insumo,))
        lotes = cursor.fetchall()

        restante = qtd_total_necessaria
        custo_insumo = 0

        for qtd_lote, custo_unit in lotes:
            if restante <= 0:
                break

            usado = min(qtd_lote, restante)
            custo_insumo += usado * custo_unit
            restante -= usado

        custo_total += custo_insumo

    conn.close()

    custo_unitario = round(custo_total / qtd, 6) if qtd > 0 else 0
    preco_sugerido = round(custo_total / 0.7, 2) if custo_total > 0 else 0

    print(f"[DEBUG] Resultado custo: unit={custo_unitario}, total={custo_total}, sugerido={preco_sugerido}")
    return jsonify({
        "unitario": custo_unitario,
        "total": round(custo_total, 2),
        "sugerido": preco_sugerido
    })

# ============================================================
# ROTAS WEB
# ============================================================

@app.route('/')
def index():
    insumos = consultar_estoque()
    conhecidos = listar_produtos()
    receitas_conhecidas = listar_receitas()
    acabados = consultar_acabados()
    data_hoje = date.today().isoformat()
    return render_template('index.html',
                           produtos=insumos,
                           conhecidos=conhecidos,
                           receitas_conhecidas=receitas_conhecidas,
                           acabados=acabados,
                           data_hoje=data_hoje)


@app.route('/add', methods=['POST'])
def add():
    nome = request.form['nome'] or request.form.get('nome_existente')
    quantidade = float(request.form['quantidade'])
    custo = float(request.form['custo'])
    data_entrada = request.form['data']
    eh_total = 'eh_total' in request.form  # True se checkbox estiver marcado
    inserir_produto_estoque(nome, quantidade, custo, data_entrada, eh_total)
    return redirect('/')


@app.route('/produzir', methods=['POST'])
def produzir():
    produto = request.form['produto']
    quantidade = float(request.form['quantidade'])

    faltantes = registrar_producao(produto, quantidade)
    if faltantes:
        msg = "❌ Não foi possível produzir: faltam "
        msg += ", ".join([f"{qtd} de {nome}" for nome, qtd in faltantes])
        flash(msg)
    else:
        flash(f"✅ Produção de {quantidade}x {produto} registrada com sucesso!")
    return redirect('/')


@app.route('/receitas')
def receitas():
    produto_filtro = request.args.get('produto', '')
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    if produto_filtro:
        cursor.execute('SELECT produto, insumo, quantidade, id FROM receitas WHERE produto=? ORDER BY produto ASC', (produto_filtro,))
    else:
        cursor.execute('SELECT produto, insumo, quantidade, id FROM receitas ORDER BY produto ASC')
    dados = cursor.fetchall()

    cursor.execute('SELECT nome FROM produtos ORDER BY nome ASC')
    insumos = [r[0] for r in cursor.fetchall()]

    cursor.execute('SELECT DISTINCT produto FROM receitas ORDER BY produto ASC')
    produtos = [r[0] for r in cursor.fetchall()]

    conn.close()
    return render_template('receitas.html',
                           receitas=dados,
                           insumos=insumos,
                           produtos=produtos,
                           produto_filtro=produto_filtro)


@app.route('/add_receita', methods=['POST'])
def add_receita():
    produto = request.form['produto']
    insumo = request.form['insumo']
    quantidade = float(request.form['quantidade'])

    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO receitas (produto, insumo, quantidade) VALUES (?, ?, ?)', (produto, insumo, quantidade))
    conn.commit()
    conn.close()
    return redirect('/receitas')


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
    app.run(debug=True)
