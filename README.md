# Vale Abrir?

Simulador web local de abertura de coleções Pokémon.

O fluxo principal é direto:

1. O usuário escolhe uma coleção no hall inicial.
2. Seleciona quantos packs quer abrir; cada pack contém 6 cartas.
3. Abre o pack e revela as seis cartas, uma por vez.
4. Vê o resumo das cartas sorteadas e o valor estimado de cada uma.

O resultado não compara gasto, lucro ou prejuízo. Ele mostra somente o valor das cartas da simulação.

Na abertura interativa, as cartas de maior raridade e valor ficam para o final de cada pack. É possível avançar por clique, toque, gesto lateral ou teclado. Simulações acima de dez packs mostram seis destaques antes do resumo completo.

## Tecnologias

- Python 3
- Flask
- SQLite
- SQLAlchemy
- Bootstrap 5
- Jinja2
- JavaScript simples

## Como instalar

No Windows, dentro da pasta do projeto:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Como executar

```powershell
python run.py
```

Depois, acesse `http://127.0.0.1:5000`.

O banco SQLite fica em `instance/database.db` e é criado automaticamente na primeira execução.

## Coleções e cartas

A tela inicial lista todas as coleções salvas, com busca por nome. Ao escolher uma coleção, o sistema reutiliza o pack de simulação existente. Se ele ainda não existir, é preparado automaticamente com as cartas locais.

Para importar ou atualizar os dados Pokémon pelo terminal:

```powershell
python importar_pokemon.py
python importar_pokemon.py --colecao-api-id sv1
python importar_pokemon.py --todos-os-packs
```

A chave da Pokémon TCG API é opcional, mas melhora os limites de uso:

```powershell
$env:POKEMON_TCG_API_KEY="sua-chave-aqui"
python run.py
```

## Valores das cartas

A simulação usa o valor salvo em cada carta do pack. Os preços podem vir do cache local, de fontes internacionais convertidas para real ou da estimativa por raridade quando não existe um preço disponível.

Para atualizar o cache de preços em lote:

```powershell
python update_card_prices.py --limit 500 --delay 1
```

Os valores exibidos são estimativas e podem variar.

## Publicar no GitHub Pages

O diretório `docs/` contém uma versão totalmente estática do simulador. Ela executa a simulação e a abertura das cartas diretamente no navegador, sem Flask ou SQLite no servidor.

O snapshot atual já contém as 174 coleções e pode ser testado localmente com:

```powershell
python -m http.server 8000 -d docs
```

Depois acesse `http://127.0.0.1:8000`.

Para atualizar os arquivos estáticos a partir do banco local e baixar coleções ausentes:

```powershell
python build_github_pages.py --fetch-missing
```

Para publicar:

1. Crie um repositório no GitHub e envie este projeto para o branch `main`.
2. No repositório, abra `Settings > Pages`.
3. Em `Build and deployment`, escolha `GitHub Actions` como fonte.
4. O workflow `.github/workflows/pages.yml` publicará automaticamente a pasta `docs/`.

Novos pushes no branch `main` atualizam o site automaticamente. O banco `instance/database.db` continua ignorado pelo Git e não é publicado.
