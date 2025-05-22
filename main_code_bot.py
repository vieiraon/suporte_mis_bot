# ============================ IMPORTAÇÕES E CONFIGURAÇÕES ============================
import logging
import time
import telebot
import random
import requests
import os
import smtplib
import pandas as pd
import pyodbc
from dotenv import load_dotenv
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from email.mime.image import MIMEImage
import re
import tempfile

# ============================ LOGGING ============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_atividade.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================ VARIÁVEIS DE AMBIENTE E CONFIG ============================
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ACESS_TOKEN = os.getenv("ACESS_TOKEN")
ARQUIVO_RELATORIOS = os.getenv("ARQUIVO_RELATORIOS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = "5432" 
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
bot = telebot.TeleBot(TOKEN)
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
app = Flask(__name__)

connection_string = (
    f"DRIVER={{PostgreSQL Unicode}};"
    f"SERVER={DB_HOST};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
)

# ============================ DICIONÁRIOS E ESTADOS =====================================
estados = {}
dados_excel = {}
datas_usuario = {}
dados_usuarios = {}
estados_login = {}
estados_senha_rid = {}
usuarios_logados = set()
usuarios_ativos = set()
senha_temporaria = {}
mensagens_usuario = {}

EMAILS_AUTORIZADOS_BLINDAGEM = {
    "leilane@online.net.br",
    "patricia.gomes@online.net.br",
    "elvys@online.net.br",
    "gabriel.vieira@onlinetelecom.com.br"
}

UPLOAD_PATH = "uploads_temporarios"
os.makedirs(UPLOAD_PATH, exist_ok=True)

# ============================ HANDLERS DE MENSAGEM ============================
def menu_comandos(chat_id):
    texto_menu = "❓Do que você precisa agora?"
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🔓 Logout", callback_data="logout"),
        InlineKeyboardButton("📚 Suporte RID", callback_data="suporte_rid")
    )
    bot.send_message(chat_id, texto_menu, parse_mode='Markdown', reply_markup=keyboard)
    logger.info(f"Usuário {chat_id} acessou o menu de comandos em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.")

# ============================ FUNÇÃO LOGAR ============================
@bot.message_handler(commands=['start'])
def start(message):
    iniciar_login(message.chat.id)
def iniciar_login(chat_id):
    if chat_id in usuarios_logados:
        bot.send_message(chat_id, "❌ Você já está logado.")
        menu_comandos(chat_id)
        return
    bot.send_message(chat_id, "👋 Você está fazendo um login.")
    estados_login[chat_id] = 'aguardando_email_login'
    bot.send_message(chat_id, "📧 Por Favor, informe seu e-mail corporativo:")
    
@bot.message_handler(func=lambda message: message.chat.id in estados_login)
def processar_logar(message):
    chat_id = message.chat.id
    texto = message.text.strip()
    mensagens_usuario.setdefault(chat_id, []).append(message.message_id)
    estado = estados_login.get(chat_id)

    if estado == 'aguardando_email_login':
        email = texto.lower()
        senha_aleatoria = str(random.randint(1, 999999)).zfill(6)

        # URLs da API
        url_funcionarios = "https://api.pontomais.com.br/external_api/v1/employees?active=true&attributes=id,cpf,first_name,last_name,email,birthdate,job_title"
        url_cargos = "https://api.pontomais.com.br/external_api/v1/job_titles?attributes=id,code,name"
        
        headers = {
            "Content-Type": "application/json",
            "access-token": ACESS_TOKEN  # Ou os.getenv("ACESS_TOKEN") se estiver usando dotenv
        }

        try:
            # Consulta cargos
            response_cargos = requests.get(url_cargos, headers=headers)
            dict_cargos = {}
            if response_cargos.status_code == 200:
                cargos = response_cargos.json().get('job_titles', [])
                dict_cargos = {str(c['id']): c['name'] for c in cargos}

            # Consulta funcionários
            response = requests.get(url_funcionarios, headers=headers)
            if response.status_code == 200:
                data = response.json()
                usuario_api = next(
                    (u for u in data.get('employees', []) if u['email'].lower() == email),
                    None
                )

                if usuario_api:
                    nome = f"{usuario_api['first_name']} {usuario_api['last_name']}"
                    cargo_id = str(usuario_api.get('job_title'))
                    cargo_nome = dict_cargos.get(cargo_id, "Cargo não identificado")

                    sucesso = enviar_email_acesso(email, senha_aleatoria, nome, cargo_nome)

                    if sucesso:
                        senha_temporaria[chat_id] = {
                            'senha': senha_aleatoria,
                            'timestamp': time.time(),
                            'email': email  # <-- SALVA O EMAIL TEMPORARIAMENTE JUNTO COM A SENHA
                        }
                        estados_login[chat_id] = 'aguardando_senha_login'
                        bot.send_message(chat_id, "✉️ Senha enviada para seu e-mail! Informe a senha aqui para prosseguir:")

                    else:
                        bot.send_message(chat_id, "❌ Erro ao enviar e-mail. Tente logar novamente.")
                        estados_login.pop(chat_id, None)
                        start(chat_id)
                else:
                    bot.send_message(chat_id, "❌ E-mail não encontrado. Tente logar novamente.")
                    estados_login.pop(chat_id, None)
                    start(chat_id)
            else:
                bot.send_message(chat_id, "❌ Erro ao consultar funcionários. Tente logar novamente.")
                estados_login.pop(chat_id, None)
                start(chat_id)

        except Exception as e:
            logger.error(f"Erro durante login: {e}")
            bot.send_message(chat_id, "❌ Ocorreu um erro no login. Tente logar novamente.")
            estados_login.pop(chat_id, None)
            iniciar_login(chat_id)

    elif estado == 'aguardando_senha_login':
        senha_informada = texto
        info_senha = senha_temporaria.get(chat_id)

        if info_senha:
            senha_correta = info_senha['senha']

            if senha_informada == senha_correta:
                usuarios_logados.add(chat_id)
    
                # SALVA O EMAIL DEFINITIVAMENTE
                dados_usuarios[chat_id] = {'email': info_senha.get('email')}
    
                bot.send_message(chat_id, "✅ Login realizado com sucesso!")
                estados_login.pop(chat_id, None)
                senha_temporaria.pop(chat_id, None)
                menu_comandos(chat_id)
                
            else:
                bot.send_message(chat_id, "❌ Senha incorreta. Tente novamente.")
        else:
            bot.send_message(chat_id, "⚠️ Nenhuma senha encontrada. Faça login novamente.")
            estados_login.pop(chat_id, None)
            start(chat_id)

@bot.message_handler(commands=['blindagem'])
def receber_arquivo(message):
    chat_id = message.chat.id
    
    # Se passou nas duas validações, permite o envio do arquivo
    bot.send_message(chat_id, "📎 Envie o arquivo Excel com as colunas de nome: contrato, celular, nome.")
    estados[message.chat.id] = 'aguardando_arquivo'

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if estados.get(message.chat.id) != 'aguardando_arquivo':
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    # Salvar arquivo
    caminho = f"arquivo_{message.chat.id}.xlsx"
    with open(caminho, 'wb') as f:
        f.write(downloaded_file)

    try:
        df = pd.read_excel(caminho)
        if not {'contrato', 'celular', 'nome'}.issubset(df.columns):
            bot.send_message(message.chat.id, "❌ O arquivo não contém todas as colunas necessárias, envie o arquivo com as colunas corretas.")
            return

        dados_excel[message.chat.id] = df
        estados[message.chat.id] = 'aguardando_data_inicial'
        bot.send_message(message.chat.id, "📅 Informe a *data inicial* no formato `DD/MM/AAAA`:", parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"Erro ao ler o arquivo: {e}")

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

def consultar_mudancas_e_gerar_excel(chat_id, df_excel, data_inicial, data_final):
    try:
        # Valida colunas mínimas
        colunas_esperadas = {'contrato', 'celular', 'nome'}
        if not colunas_esperadas.issubset(df_excel.columns):
            bot.send_message(chat_id, "❌ A planilha não contém todas as colunas necessárias: contrato, celular, nome.")
            return

        # Limpa os contratos
        df_excel['contrato'] = df_excel['contrato'].astype(str).str.strip()
        contratos = df_excel['contrato'].tolist()

        if not contratos:
            bot.send_message(chat_id, "⚠️ Nenhum contrato encontrado na planilha enviada.")
            return

        # Conexão com banco
        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()

        # Prepara a query
        data_inicial_str = data_inicial.strftime('%Y-%m-%d')
        data_final_str = data_final.strftime('%Y-%m-%d')
        placeholder = ','.join('?' for _ in contratos)

        query = f"""
            SELECT DISTINCT ch_contrato
            FROM mudancas_plano
            WHERE dh_alteracao BETWEEN ? AND ?
            AND ch_contrato IN ({placeholder})
        """

        params = [data_inicial_str, data_final_str] + contratos
        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Contratos com mudança
        contratos_com_mudanca = {str(row[0]).strip() for row in rows}
        df_com_mudanca = df_excel[df_excel['contrato'].isin(contratos_com_mudanca)]
        df_sem_mudanca = df_excel[~df_excel['contrato'].isin(contratos_com_mudanca)]

        # Gera Excel temporário
        hoje = datetime.now().strftime("%d_%m_%Y")
        nome_arquivo = f"relatorio_mudancas_{hoje}.xlsx"
        caminho_arquivo = os.path.join(tempfile.gettempdir(), nome_arquivo)

        with pd.ExcelWriter(caminho_arquivo, engine='xlsxwriter') as writer:
            df_com_mudanca.to_excel(writer, index=False, sheet_name='Com Mudança')
            df_sem_mudanca.to_excel(writer, index=False, sheet_name='Sem Mudança')

        # Mensagem final
        total_com_mudanca = len(df_com_mudanca)
        total_planilha = len(df_excel)
        total_sem_mudanca = len(df_sem_mudanca)

        data_inicial_br = data_inicial.strftime('%d/%m/%Y')
        data_final_br = data_final.strftime('%d/%m/%Y')

        mensagem = (
            f"📊 Resultado da análise no período *{data_inicial_br}* a *{data_final_br}*:\n\n"
            f"📄 Total de contratos na planilha: *{total_planilha}*\n"
            f"✅ Com mudança de plano: *{total_com_mudanca}*\n"
            f"❌ Sem mudança de plano: *{total_sem_mudanca}*\n\n"
            f"📁 Enviando planilha com os resultados..."
        )
        bot.send_message(chat_id, mensagem, parse_mode="Markdown")
        with open(caminho_arquivo, 'rb') as f:
            bot.send_document(chat_id, f, caption="📎 Planilha com resultados da análise")

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Erro ao consultar mudanças de plano: {str(e)}")

    finally:
        try:
            cursor.close()
            connection.close()
        except:
            pass

        # Remove arquivo temporário
        try:
            os.remove(caminho_arquivo)
        except:
            pass

    time.sleep(2)
    menu_comandos(chat_id)

@bot.message_handler(func=lambda m: estados.get(m.chat.id) in ['aguardando_data_inicial', 'aguardando_data_final'])
def receber_datas(message):
    chat_id = message.chat.id
    texto = message.text.strip()

    try:
        data = datetime.strptime(texto, '%d/%m/%Y')

        if estados[chat_id] == 'aguardando_data_inicial':
            datas_usuario[chat_id] = {'data_inicial': data}
            estados[chat_id] = 'aguardando_data_final'
            bot.send_message(chat_id, "Agora informe a *data final* no formato `DD/MM/AAAA`:", parse_mode="Markdown")
        else:
            datas_usuario[chat_id]['data_final'] = data
            df = dados_excel[chat_id]
            data_i = datas_usuario[chat_id]['data_inicial']
            data_f = datas_usuario[chat_id]['data_final']

            bot.send_message(chat_id, "⏳ Consultando mudanças de plano...")
            consultar_mudancas_e_gerar_excel(chat_id, df, data_i, data_f)

            estados.pop(chat_id)
            dados_excel.pop(chat_id)
            datas_usuario.pop(chat_id)

    except ValueError:
        bot.send_message(chat_id, "❌ Data inválida. Use o formato `DD/MM/AAAA`.")

#----------------------CONSULTA AO BANCO E VALIDA O ESQUECI SENHA-------------------------#
def escape_markdown_v2(text):
    return re.sub(r'([_\*\[\]\(\)~`>\#\+\-\=\|\{\}\.\!\\])', r'\\\1', text)
        
def buscar_senha_por_email(chat_id, email):
    try:
        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()

        query = """
            SELECT senha
            FROM cadastro_rid
            WHERE email_corp = ?
            ORDER BY id DESC
            LIMIT 1
        """
        cursor.execute(query, (email,))
        row = cursor.fetchone()

        if row and row[0]:
            # Garantir que a senha é tratada como string
            senha = str(row[0])  # Converter para string
            senha_escapada = escape_markdown_v2(senha)  # Aplicar o escape

            bot.send_message(chat_id, "❗Lembre-se:\nESTA SENHA É DE TOTAL RESPONSABILIDADE SUA, PORTANTO, CUIDADO COM ESSA INFORMAÇÃO.")
            time.sleep(3)
            bot.send_message(
                chat_id,
                f"🔑 Sua senha do RID é:\n||{senha_escapada}||",  # Usar a senha escapada
                parse_mode="MarkdownV2"
            )
            time.sleep(1)
            logger.info(f"Usuário {chat_id} recebeu a senha do RID em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.")
            menu_comandos(chat_id)
        else:
            bot.send_message(chat_id, "❌ Não encontramos este e-mail no cadastro RID.")
            logger.warning(f"Usuário {chat_id} tentou recuperação, mas o e-mail não foi encontrado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.")
            menu_comandos(chat_id)
    except pyodbc.Error as e:
        bot.send_message(chat_id, "⚠️ Erro ao consultar a senha. Tente novamente mais tarde.")
        print(f"Erro técnico (Banco): {e}")
        menu_comandos(chat_id)
    except Exception as ex:
        bot.send_message(chat_id, "⚠️ Erro inesperado.")
        print(f"Erro técnico (Geral): {ex}")
        menu_comandos(chat_id)
    finally:
        try:
            cursor.close()
            connection.close()
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data == "esqueci_senha")
def esqueci_senha(call):
    chat_id = call.message.chat.id

    if chat_id not in usuarios_logados:
        bot.send_message(chat_id, "❌ Você precisa estar logado para usar essa função.")
        iniciar_login(chat_id)
        return

    # Tenta buscar o e-mail salvo
    email_usuario = dados_usuarios.get(chat_id, {}).get('email')

    if email_usuario:
        # Se tiver o e-mail salvo, já tenta buscar a senha
        buscar_senha_por_email(chat_id, email_usuario)
        logger.info(f"Usuário {chat_id} o email do Usuário foi validado e sua senha do RID foi repassado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.")
    else:
        # Se não tiver logado ele da erro
        bot.send_message(chat_id, "❗Não encontrei seu e-mail cadastrado.\n🟡Certifique que você esta logado aqui com o email do RID ou que tenha um Cadastro Válido.")
        menu_comandos(chat_id)
        logger.warning(f"Usuário {chat_id} não esta logado com o email do RID ou não tem cadastro. Validado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.")

@bot.callback_query_handler(func=lambda call: call.data == "cadastro_rid")
def cadastro_rid(call):
    chat_id = call.message.chat.id

    if chat_id not in usuarios_logados:
        bot.send_message(chat_id, "❌ Você precisa estar logado para usar essa função.")
        iniciar_login(chat_id)
        return
    
    bot.send_message(chat_id, "⁉️ *Seu Nome não aparece no BI em nenhuma das ABAs como mostrado na foto abaixo?*", parse_mode='Markdown')

# Envia a imagem do diretório local
    caminho_absoluto = os.path.join(os.path.dirname(__file__), f'img\\nome_nao_aparece.png')
    with open(caminho_absoluto, 'rb') as photo:
        bot.send_photo(chat_id, photo)
    time.sleep(2)
    bot.send_message(chat_id, 
        "✅ *Recomendamos seguir atentamente o checklist abaixo antes de prosseguir:*\n\n"
        "1️⃣ *Você já preencheu o formulário Cadastro RID 2025?*\n"
        "Se ainda não preencheu, clique no botão abaixo para realizar seu cadastro.\n\n"
        "2️⃣ *Após o cadastro, você aguardou a próxima atualização do BI?*\n"
        "_Horários de atualização:_\n"
        "🕡 *06:30* | 🕗 *08:00* | 🕧 *12:30* | 🕠 *17:30*\n\n"
        "3️⃣ *Você preencheu corretamente o campo “Login MK” no formulário?*\n"
        "Certifique-se de usar apenas letras minúsculas, exatamente como aparece no sistema.\n"
        "📌 Exemplo: `nome.sobrenome`\n\n"
        "4️⃣ *Seu cargo está corretamente associado à sua equipe no sistema PontoMais?*\n"
        "Verifique se o cargo registrado corresponde à função e à equipe à qual você pertence.\n"
        "📌 Exemplo: `ANALISTA DO BOT DE SUPORTE MIS`\n\n",
        parse_mode='Markdown'
    )
    time.sleep(2)
    botao_cadastro = InlineKeyboardButton(
    text="👉 CLIQUE AQUI PARA CADASTRAR-SE 👈", 
    url="https://abrir.link/OGKyq"
    )
    keyboard = [[botao_cadastro]]
    markup_cadastro = InlineKeyboardMarkup(keyboard)

    bot.send_message(
        chat_id=chat_id,
        text=(
            "⚠️ *Mesmo após seguir todas as etapas acima, seu nome ainda não apareceu?*\n"
            "Recomendamos que faça um *novo cadastro* para garantir que tudo esteja correto."
        ),
        parse_mode="Markdown",
        reply_markup=markup_cadastro
    )
    time.sleep(2)
    menu_comandos(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "contestar_comissao")
def contestar_comissao(call):
    chat_id = call.message.chat.id
    bot.send_message(chat_id,
        "🤔Hummm, não aconteceu nada, parece que nossos DEVs ainda não fizeram essa função rodar.",
        parse_mode='Markdown'
    )
    time.sleep(2)
    menu_comandos(chat_id)

#----------------- LOGOUT --------------------$
def logout(chat_id):
    if chat_id in usuarios_logados:
        usuarios_logados.remove(chat_id)
        bot.send_message(chat_id, "🔐 Você foi deslogado com sucesso!")
        logger.info(f"Usuário {chat_id} foi deslogado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.")
        start(chat_id)
    else:
        bot.send_message(chat_id, "❌ Você não está logado no momento.")
        logger.warning(f"Tentativa de logout falhada: Usuário {chat_id} não está logado. Registro em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        start(chat_id)

# ------------------- CALLBACK E BOTÕES DO TELEGRAM ------------------#
@bot.callback_query_handler(func=lambda call: call.data == "iniciar_login")
def iniciar_login_callback(call):
    bot.answer_callback_query(call.id)
    start(call.message)

@bot.callback_query_handler(func=lambda call: True)
def tratar_callback(call):
    chat_id = call.message.chat.id
    data = call.data

    if data == "start":
        start(call.message)

    elif data == "logout":
        if chat_id in usuarios_logados:
            usuarios_logados.remove(chat_id)
            bot.send_message(chat_id, "🚪 Logout realizado com sucesso!")
            start(call.message)
        else:
            bot.send_message(chat_id, "❌ Você não está logado.")
            start(call.message)

    elif data == "suporte_rid":
        if chat_id in usuarios_logados:
            keyboard = InlineKeyboardMarkup(row_width=1)
            keyboard.add(
                InlineKeyboardButton("🔑 Esqueci a Senha do Meu RID", callback_data="esqueci_senha"),
                InlineKeyboardButton("👤 Não apareço no RID/Sem Cadastro", callback_data="cadastro_rid"),
                InlineKeyboardButton("💵 Contestar Comissão", callback_data="contestar_comissao"),
                InlineKeyboardButton("🔙 Voltar ao Menu Principal", callback_data="menu_comandos")
            )
            bot.send_message(chat_id, "📚 Suporte RID\n👇Escolha uma opção👇", parse_mode="Markdown", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "❌ Você precisa estar logado para acessar a ajuda do RID.")
            start(call.message)
    
    elif data == "menu_comandos":
        menu_comandos(chat_id)

# ============================ FUNÇÃO ENVIAR EMAIL ============================
def enviar_email_acesso(destinatario, senha, nome_usuario, cargo):
    remetente = 'gabriel.vieira@vianalise.com'
    senha_app = 'bafg axhf kqfk pmjw'

    if not nome_usuario:
        nome_usuario = 'Usuário'

    msg = MIMEMultipart('related')
    msg['From'] = f'Suporte MIS <{remetente}>'
    msg['To'] = destinatario
    msg['Subject'] = 'Senha de Acesso - Suporte MIS'

    corpo = f"""
<html>
<head>
  <style>
    body {{
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      color: #333;
      padding: 20px;
    }}
    .container {{
      background-color: #ebebeb;
      border-radius: 10px;
      padding: 30px;
      max-width: 600px;
      margin: auto;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
      border-top: 5px solid #D32F2F;
    }}
    .header-img {{
      width: 100%;
      max-width: 200px;
      margin: 0 auto 20px auto;
      display: block;
    }}
    .titulo {{
      color: #d32f2f;
      font-size: 22px;
      font-weight: bold;
      text-align: center;
      margin-bottom: 20px;
    }}
    .mensagem-box {{
      background-color: #fff4f4;
      border-left: 5px solid #D32F2F;
      padding: 15px;
      margin: 20px 0;
      font-size: 20px;
      color: #c62828;
      border-radius: 5px;
    }}
    .assinatura-box {{
      margin-top: 40px;
      border-top: 1px dashed #ddd;
      padding-top: 20px;
      text-align: center;
    }}
    .assinatura-nome {{
      font-size: 16px;
      font-weight: 600;
      color: #D32F2F;
      text-transform: uppercase;
    }}
    .botao-bot {{
  display: inline-block;
  padding: 10px 18px;
  font-size: 14px;
  background-color: #FFFFFF;
  color: #D32F2F;
  text-decoration: none;
  border-radius: 25px;
  font-weight: bold;
  box-shadow: 0 2px 6px rgba(0,0,0,0.15);
  border: 3px solid #D32F2F;
  transition: all 0.2s ease;  /* <- Faz tudo suavizar */
    }}
    .botao-bot:hover {{
  background-color: #f0f0f0;
  transform: scale(0.97);      /* <- Leve encolhimento */
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);  /* <- Sombra mais baixa */
    }}
  </style>
</head>
<body>
  <div class="container">
    <img src="cid:teleco" class="header-img" alt="Equipe Suporte MIS">
    <p class="titulo">Olá, {nome_usuario}!</p>
    <p style="text-align: center;"><strong>Você está recebendo uma senha temporária para acessar o Chat de Suporte MIS.</strong></p>
    <div class="mensagem-box">
      🔐 Sua senha de acesso é: <strong>{senha}</strong>
    </div>
    <p style="text-align: center; font-size: 16px"><strong>⚠️ Esta senha é válida por até 60 segundos e apenas para este acesso atual ⚠️</strong></p>
    <div class="assinatura-box">
      <p class="assinatura-nome"><strong>Equipe de Suporte MIS ONLINE TELECOM</strong></p>
      <a class="botao-bot" href="https://t.me/mis_testes_bot" target="_blank">💬 Acesse o Suporte via Telegram</a>
    </div>
  </div>
</body>
</html>
"""
    # Adiciona parte alternativa (HTML)
    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(corpo, 'html'))

    # Adiciona a imagem corretamente com Content-ID (depois do HTML)
    caminho_absoluto = os.path.join(os.path.dirname(__file__), f'img\\teleco.png')
    with open(caminho_absoluto, 'rb') as img_file:
        img = MIMEImage(img_file.read())
        img.add_header('Content-ID', '<teleco>') 
        img.add_header('Content-Disposition', 'inline', filename="teleco.png")
        msg.attach(img)

    # Envia o e-mail
    try:
        servidor = smtplib.SMTP('smtp.gmail.com', 587)
        servidor.starttls()
        servidor.login(remetente, senha_app)
        servidor.send_message(msg)
        servidor.quit()
        return True
    except Exception as e:
        logger.warning(f"Ocorreu um erro enviar o email para o email {remetente}: {e} em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.")
    return False

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.before_first_request
def setup_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"hhttps://suporte-mis-bot-z16u.onrender.com/{TOKEN}")
    print(f"Webhook setado às {datetime.now().strftime('%H:%M:%S')}")

# Inicia o bot normalmente
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # PORT é obrigatório no Render
    app.run(host="0.0.0.0", port=port)
