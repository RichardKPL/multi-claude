<div align="center">

<img src="recursos/icone.png" width="112" alt="Multi Claude">

# Multi Claude

**Várias contas do Claude Desktop, cada uma na sua janela — ao mesmo tempo.**

[![Download](https://img.shields.io/github/v/release/RichardKPL/multi-claude?label=download&color=d97757&style=for-the-badge)](https://github.com/RichardKPL/multi-claude/releases/latest/download/Multi-Claude-Portable.exe)
[![Licença GPL-3.0](https://img.shields.io/badge/licen%C3%A7a-GPL--3.0-1f1e1d?style=for-the-badge)](LICENSE)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4?style=for-the-badge&logo=windows)](#requisitos)
[![Portátil](https://img.shields.io/badge/port%C3%A1til-sem%20instala%C3%A7%C3%A3o-5fa85e?style=for-the-badge)](#download)

[**Site**](https://richardkpl.github.io/multi-claude/) ·
[**Download**](https://github.com/RichardKPL/multi-claude/releases/latest) ·
[**Como funciona**](#como-funciona) ·
[**English**](#english)

<img src="docs/img/principal-claro.png" alt="Tela principal do Multi Claude" width="860">

</div>

---

## ✨ Recursos

| | |
|---|---|
| 👥 **Perfis ilimitados** | Cada perfil é um Claude Desktop separado, com login, sessões e configurações próprias. |
| 🔐 **Login com Google automático** | Clique em *Entrar*, escolha a conta no navegador e pronto — o login vai para o perfil certo, sem abrir o Claude principal. |
| 🟢 **Status ao vivo** | Veja quais perfis estão conectados e quais estão abertos; abra e feche cada um com um clique. |
| 🖼️ **Fotos de perfil** | Galeria inclusa + envio das suas imagens. Qualquer imagem na pasta `profile_pictures` vira opção. |
| 🎨 **Claro, Escuro ou Sistema** | Acompanha o tema do Windows ao vivo, inclusive a barra de título. |
| 🌍 **10 idiomas** | Português, English, Español, Français, Deutsch, Italiano, Русский, 日本語, 中文, 한국어. |
| 📦 **100% portátil** | Um único `.exe`. Todos os dados ficam ao lado dele — leve num pendrive. |
| ⇩ **Importar perfis** | Encontra perfis do Claude que já existem na máquina (ou outro `perfis.db`) e importa. |
| 🧨 **Zona de perigo** | Apaga todos os dados do Multi Claude com uma confirmação digitada. |
| 📐 **Layout responsivo** | Uma ou duas colunas conforme o tamanho da janela; lembra posição e tamanho. |

<div align="center">
<img src="docs/img/principal-escuro.png" width="420" alt="Tema escuro">
<img src="docs/img/fotos.png" width="380" alt="Fotos de perfil">
</div>

## ⬇️ Download

1. Baixe **[`Multi-Claude-Portable.exe`](https://github.com/RichardKPL/multi-claude/releases/latest/download/Multi-Claude-Portable.exe)**.
2. Coloque numa pasta só dele (ex.: `Documentos\Multi Claude`) — é lá que ficarão os seus dados.
3. Abra. Na primeira vez ele pergunta o idioma e oferece importar perfis que já existam.

> O Windows SmartScreen pode avisar que o arquivo é de um editor desconhecido (o executável não é assinado). Clique em **Mais informações → Executar assim mesmo**. O código-fonte completo está neste repositório, se quiser conferir ou gerar o seu próprio `.exe`.

### Requisitos

- Windows 10 ou 11
- [Claude Desktop](https://claude.ai/download) instalado

## 🚀 Como usar

1. **+ Novo perfil** → dê um nome e escolha uma foto.
2. **Entrar** → na janela do Claude que abrir, clique em *Continuar com Google* e escolha a conta.
   Se o navegador perguntar, clique em *Abrir Claude*. O resto é automático.
3. Depois de logado, use **Abrir** / **Fechar**. No menu **⋯** ficam *Foto de perfil*, *Renomear*, *Pasta de dados*, *Sair da conta* e *Excluir*.

<div align="center">
<img src="docs/img/boas-vindas.png" width="300" alt="Boas-vindas">
<img src="docs/img/configuracoes.png" width="260" alt="Configurações">
</div>

## ⚙️ Como funciona

- Cada perfil roda o Claude Desktop com `--user-data-dir=<pasta do perfil>`, então logins e sessões ficam isolados.
- **Login:** o navegador devolve o login por um link `claude://`. O Claude da Microsoft Store registra esse protocolo no próprio pacote, então o Windows sempre o entrega ao Claude principal — por um instante ele inicia um `Claude.exe` com o link na linha de comando. Durante o login, o Multi Claude observa os processos novos, lê esse link, encerra o processo passageiro (para o Claude principal não abrir) e entrega o link ao Claude do perfil.
  Nada é enviado para fora do seu computador.
- **Status:** "conectado" vem do log do próprio Claude do perfil; "aberto" vem dos processos em execução.
- **Sair da conta** fecha o Claude do perfil e apaga cookies e tokens só daquele perfil.

### Onde ficam os dados (modo portátil)

```
Multi-Claude-Portable.exe
perfis.db            ← perfis, idioma, tema (SQLite)
log.txt              ← registro de diagnóstico
dados\<perfil>\      ← dados do Claude de cada perfil
profile_pictures\    ← fotos padrão + as que você enviar (usuario_*)
```

Os caminhos dentro da pasta do programa são salvos como relativos — dá para mover a pasta inteira de lugar ou de computador.

## 🛠️ Rodar e compilar a partir do código

```bash
pip install pillow pyinstaller
pythonw "Multi Claude.pyw"          # roda direto
python recursos/build_exe.py        # gera dist/Multi Claude.exe (portátil, arquivo único)
```

O `.exe` gerado leva apenas o ícone e as fotos padrão — nenhum dado de usuário.

```
Multi Claude.pyw        código do programa
recursos/               ícone e script de build
profile_pictures/       fotos de perfil padrão
docs/                   site (GitHub Pages)
LICENSE · NOTICE        licença GPL-3.0 + termos de atribuição
```

## 📄 Licença e créditos

**Multi Claude © 2026 [Richard KPL](https://github.com/RichardKPL)** — software livre sob a **[GPL-3.0](LICENSE)** com os termos adicionais do arquivo **[NOTICE](NOTICE)**.

Você pode usar, estudar, modificar e redistribuir. Se publicar uma versão modificada, ela **precisa**:

- continuar com código aberto, sob a GPL-3.0;
- manter visível no programa e no README: *"Baseado no Multi Claude, criado por Richard KPL"* com link para este repositório;
- manter os arquivos `LICENSE` e `NOTICE`;
- deixar claro que é uma versão modificada.

> **Aviso:** "Claude" e "Claude Desktop" são marcas da Anthropic, PBC. O Multi Claude é um projeto independente e **não tem ligação, aprovação ou patrocínio da Anthropic**. Use respeitando os [termos de uso do Claude](https://www.anthropic.com/legal/consumer-terms).

---

## English

**Multi Claude** runs several Claude Desktop accounts side by side, each in its own window.

- Unlimited profiles, each one an isolated Claude Desktop (`--user-data-dir`).
- Automatic Google sign-in routed to the right profile, without popping up your main Claude.
- Live status (signed in / open), open & close per profile, sign out, profile pictures.
- Light / Dark / System theme, 10 languages, responsive layout.
- Fully portable single `.exe` — all data lives next to it. Import existing profiles; erase everything from the danger zone.

**[Download Multi-Claude-Portable.exe](https://github.com/RichardKPL/multi-claude/releases/latest/download/Multi-Claude-Portable.exe)** · Windows 10/11 · requires [Claude Desktop](https://claude.ai/download).

Licensed under **GPL-3.0** with additional attribution terms ([NOTICE](NOTICE)): forks and modified versions must stay open source and keep the credit *"Based on Multi Claude, created by Richard KPL"* visible in the app and README.
Not affiliated with Anthropic.
