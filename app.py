import streamlit as st
import pandas as pd
import numpy as np
import base64
import urllib.request
import io
import unicodedata

def normalize_text(text):
    """Remove acentos e caracteres especiais de uma string."""
    if not isinstance(text, str):
        return ""
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower()

def normalize_columns(df):
    """Padroniza os nomes das colunas para facilitar a busca (remove espaços, coloca em maiúsculas)."""
    df.columns = [normalize_text(str(c)).strip().upper() for c in df.columns]
    return df

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="FORNECEDORES PAV",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização
st.markdown("""
<style>
    .main-title {
        font-family: 'Outfit', 'Inter', sans-serif;
        font-size: 2.8rem;
        font-weight: 800;
        background: linear-gradient(90deg, #007AFF, #00C9FF, #00E676);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 1.1rem;
        color: #7d8590;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🎬 FORNECEDORES PAV</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Filtre e analise a sua base de dados de audiovisual de forma rápida.</div>', unsafe_allow_html=True)


# --- 1. ENTRADA DE DADOS (Google Sheets Automático) ---
st.sidebar.markdown("### 📥 Fonte de Dados")
st.sidebar.success("Conectado ao Google Sheets 🟢")

if st.sidebar.button("🔄 Atualizar Planilha Agora"):
    st.cache_data.clear()

linha_cabecalho = st.sidebar.number_input(
    "Linha do Cabeçalho no Excel:", 
    min_value=1, 
    value=4, 
    help="Informe em qual linha da planilha estão escritos os nomes das colunas (NOME, CARGO, etc). O padrão ajustado é 4."
)

GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1Q9nSJg2_Ps0VLXivYgNpXUL6m-iodOgO-ZswE__zvhc/export?format=xlsx"

@st.cache_data(ttl=60)
def load_google_sheet(url, header_idx):
    """Carrega os dados da nuvem com cache de 60 segundos."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            excel_bytes = response.read()
        return pd.read_excel(io.BytesIO(excel_bytes), header=header_idx)
    except Exception as e:
        st.sidebar.error(f"Erro ao conectar com a planilha: {e}")
        return None

with st.spinner("Sincronizando dados ao vivo..."):
    df = load_google_sheet(GOOGLE_SHEETS_URL, header_idx=linha_cabecalho - 1)

origem_dados = "Google Sheets (Conectado)"

# Se os dados foram carregados corretamente
if df is not None:
    df = normalize_columns(df)
    
    # 2. ESTRUTURA DAS NOVAS COLUNAS
    colunas_esperadas = ["NOME", "CARGO", "LOCAL", "TAG", "CONTATO", "ULTIMO PROJETO GLOBO", "CANAL", "DATA"]
    
    # Verifica quais colunas faltam
    missing_cols = [c for c in colunas_esperadas if c not in df.columns]
    
    if missing_cols:
        st.warning(f"⚠️ **Algumas colunas esperadas não foram encontradas:** {', '.join(missing_cols)}")
        if len(missing_cols) == len(colunas_esperadas):
            st.error("🚨 **NENHUMA das colunas esperadas foi encontrada!** A tabela aparecerá em branco. Verifique se o cabeçalho da sua planilha está na primeira linha e se os nomes correspondem.")
        with st.expander("Clique aqui para ver as colunas que o sistema conseguiu ler da sua planilha"):
            st.write("Colunas detectadas:", list(df.columns))
            st.write("Se o cabeçalho estiver na linha 2 ou 3 do Excel, o sistema pode ter lido a linha errada.")
            
    # Adiciona colunas faltantes para evitar erro
    for c in colunas_esperadas:
        if c not in df.columns:
            df[c] = ""
            
    # Garante que exibiremos as colunas exatas na ordem requerida
    df = df[colunas_esperadas]
    
    # --- TRATAMENTO DE CÉLULAS MESCLADAS (MERGED CELLS) ---
    # Pandas lê células mescladas colocando o valor na primeira linha e NaN nas demais.
    # Vamos agrupar as linhas adjacentes que pertencem à mesma pessoa.
    
    # Trata valores vazios como NaN para a coluna NOME
    nome_series = df['NOME'].replace(r'^\s*$', np.nan, regex=True)
    
    # Cria um ID único de bloco que incrementa a cada NOME não nulo encontrado
    block_id = nome_series.notna().cumsum()
    
    # Remove as linhas do topo que não pertencem a nenhum fornecedor (block_id == 0)
    df = df[block_id > 0]
    block_id = block_id[block_id > 0]
    
    if not df.empty:
        # Regras de agrupamento: pega o primeiro valor válido para todas as colunas
        agg_rules = {c: 'first' for c in colunas_esperadas}
        # Para a coluna TAG, junta todas as tags do bloco com vírgula, removendo duplicadas
        agg_rules['TAG'] = lambda x: ', '.join(dict.fromkeys([str(t).strip() for t in x if pd.notna(t) and str(t).strip() != "" and str(t).strip().lower() != "nan"]))
        
        df = df.groupby(block_id, as_index=False).agg(agg_rules)
    
    # Tratar os meses (Data do último trabalho)
    data_oficial = pd.to_datetime(df["DATA"], errors='coerce', dayfirst=True)
    data_projeto = pd.to_datetime(df["ULTIMO PROJETO GLOBO"], errors='coerce', dayfirst=True)
    data_canal = pd.to_datetime(df["CANAL"], errors='coerce', dayfirst=True)
    
    df["Data_Validada"] = data_oficial.fillna(data_projeto).fillna(data_canal)
    hoje = pd.Timestamp.today()
    
    # Calcula a diferença em meses apenas para as linhas com data válida
    df["Meses_Ociosos"] = (hoje.year - df["Data_Validada"].dt.year) * 12 + (hoje.month - df["Data_Validada"].dt.month)
    df["Meses_Ociosos"] = df["Meses_Ociosos"].fillna(-1).astype(int)
    
    def formatar_tempo(meses):
        if meses == -1:
            return "Desconhecido"
        elif meses == 0:
            return "Menos de 1 mês"
        elif meses == 1:
            return "1 mês"
        else:
            return f"{meses} meses"
            
    df["TEMPO SEM SERVIÇO"] = df["Meses_Ociosos"].apply(formatar_tempo)
    
    
    # --- 3. NOVOS FILTROS INTERATIVOS ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎛️ Filtros de Busca")
    
    
    # Filtro 1: Nome (Texto)
    nome_busca = st.sidebar.text_input("Nome (busca):", help="Digite parte do nome do fornecedor")
    
    # Filtro 2: Cargo (Multiselect Dinâmico)
    opcoes_cargo = sorted([str(c).strip() for c in df["CARGO"].dropna().unique() if str(c).strip() != ""])
    cargo_selecionado = st.sidebar.multiselect("Cargo:", options=opcoes_cargo)

    # Filtro 3: Local (Multiselect)
    opcoes_local = sorted([str(loc).strip() for loc in df["LOCAL"].dropna().unique() if str(loc).strip() != ""])
    local_selecionado = st.sidebar.multiselect("Local:", options=opcoes_local)

    # Filtro 4: Tags (Multiselect)
    todas_tags = set()
    for tags in df["TAG"].dropna().astype(str):
        for tag in tags.split(','):
            if tag.strip():
                todas_tags.add(tag.strip())
    opcoes_tags = sorted(list(todas_tags))
    tags_selecionadas = st.sidebar.multiselect("Tags Específicas:", options=opcoes_tags)

    # Filtro 4: Tempo sem Serviço (Slider)
    meses_validos = df[df["Meses_Ociosos"] >= 0]["Meses_Ociosos"]
    max_meses = int(meses_validos.max()) if not meses_validos.empty else 60
    max_meses = max(max_meses, 1)

    limite_meses = st.sidebar.slider(
        "Tempo Máx. Sem Serviço (meses):",
        min_value=0,
        max_value=max_meses + 12,
        value=max_meses + 12
    )
    
    incluir_sem_data = st.sidebar.checkbox("Incluir datas desconhecidas", value=True)

    
    # --- APLICANDO FILTROS ---
    df_filtrado = df.copy()

    if nome_busca:
        df_filtrado = df_filtrado[df_filtrado["NOME"].astype(str).str.contains(nome_busca, case=False, na=False)]

    if cargo_selecionado:
        # Busca correspondência para lidar com formatações ou múltiplos cargos
        df_filtrado = df_filtrado[df_filtrado["CARGO"].astype(str).apply(
            lambda x: any(c.lower() in str(x).lower() for c in cargo_selecionado)
        )]

    if local_selecionado:
        # Verifica se o texto na coluna LOCAL bate com as seleções
        # Como pode haver múltiplos locais ou formatações diferentes, buscamos correspondência
        df_filtrado = df_filtrado[df_filtrado["LOCAL"].astype(str).apply(
            lambda x: any(l.lower() in str(x).lower() for l in local_selecionado)
        )]

    if tags_selecionadas:
        # A tag no excel pode ser "ágil, organizado, bom de jogo"
        # Precisamos ver se ALGUMA tag selecionada está dentro do texto
        df_filtrado = df_filtrado[df_filtrado["TAG"].astype(str).apply(
            lambda x: any(t.lower() in str(x).lower() for t in tags_selecionadas)
        )]

    # Aplicar o filtro de meses
    if incluir_sem_data:
        df_filtrado = df_filtrado[
            (df_filtrado["Meses_Ociosos"] <= limite_meses) | (df_filtrado["Meses_Ociosos"] == -1)
        ]
    else:
        df_filtrado = df_filtrado[
            (df_filtrado["Meses_Ociosos"] >= 0) & (df_filtrado["Meses_Ociosos"] <= limite_meses)
        ]

    
    # Ordenar em ordem alfabética pelo NOME
    if not df_filtrado.empty:
        df_filtrado = df_filtrado.sort_values(by="NOME", ascending=True)

    # --- 4. EXIBIÇÃO DOS RESULTADOS ---
    st.markdown(f"**Registros encontrados:** {len(df_filtrado)}")
    
    if not df_filtrado.empty:
        # Remove as colunas auxiliares de data e meses ociosos para exibição limpa
        df_visualizacao = df_filtrado[colunas_esperadas + ["TEMPO SEM SERVIÇO"]]
        
        st.dataframe(
            df_visualizacao,
            use_container_width=True,
            hide_index=True
        )
        
        # Opção de baixar planilha
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df_visualizacao.to_excel(writer, index=False)
            
        st.download_button(
            label="📥 Baixar Excel Filtrado",
            data=buffer.getvalue(),
            file_name="fornecedores_filtrados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("Nenhum fornecedor encontrado com os filtros selecionados.")
        
    st.caption(f"Origem dos dados: {origem_dados}")

else:
    st.info("👈 Selecione a forma de entrada de dados e carregue uma planilha para começar.")
