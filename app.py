from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import date

app = Flask(__name__)

# --- Banco de dados ---
def inicializar_banco():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    # Tabela de produtos conhecidos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        )
    ''')

    # Tabela de registros de estoque
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            custo_unit REAL NOT NULL,
            data_entrada TEXT NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


# --- Funções utilitárias ---
def inserir_produto_estoque(nome, quantidade, custo_unit, data_entrada):
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()

    # 1️⃣ verifica se o produto já existe na tabela de produtos conhecidos
    cursor.execute('SELECT id FROM produtos WHERE nome = ?', (nome,))
    existe = cursor.fetchone()

    # 2️⃣ se não existe, insere
    if not existe:
        cursor.execute('INSERT INTO produtos (nome) VALUES (?)', (nome,))

    # 3️⃣ registra a entrada no estoque
    cursor.execute('INSERT INTO estoque (nome, quantidade, custo_unit, data_entrada) VALUES (?, ?, ?, ?)',
                   (nome, quantidade, custo_unit, data_entrada))

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


# --- Rotas ---
@app.route('/')
def index():
    produtos = consultar_estoque()
    conhecidos = listar_produtos()
    data_hoje = date.today().isoformat()
    return render_template('index.html', produtos=produtos, conhecidos=conhecidos, data_hoje=data_hoje)


@app.route('/add', methods=['POST'])
def add():
    nome = request.form['nome']
    quantidade = int(request.form['quantidade'])
    custo = float(request.form['custo'])
    data_entrada = request.form['data']
    inserir_produto_estoque(nome, quantidade, custo, data_entrada)
    return redirect('/')


# --- Executar ---
if __name__ == '__main__':
    inicializar_banco()
    app.run(debug=True)
