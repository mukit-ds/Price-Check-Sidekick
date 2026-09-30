# 🛒 Price-Check Sidekick

An AI-powered shopping assistant that helps you decide whether a product is worth buying.

Simply **paste a product name or product link**, and Price-Check Sidekick searches the web, analyzes available information, and gives you a clear:

* 🟢 **BUY** — Looks like a good deal
* 🟡 **WAIT** — Better to wait for a better price, newer model, or more information
* 🔴 **SKIP** — The price or product doesn't look worthwhile

It also provides **seller information and alternative products** to help you make a more informed decision.

---

## ✨ Features

* 🔎 Search the web for current product information
* 🤖 AI-powered product analysis
* 💰 Evaluate whether the current price is reasonable
* 🛍️ Identify available sellers
* 🔄 Suggest alternative products
* 📊 Provide a simple BUY / WAIT / SKIP recommendation
* 🎛️ Adjustable web-search limit for cost control
* 🧠 Selectable OpenAI model from the sidebar
* ⚡ Streamlit-based interactive interface

---

## 🏗️ How It Works

```text
Product Name / URL
        │
        ▼
┌───────────────────┐
│  Price-Check      │
│     Sidekick      │
└─────────┬─────────┘
          │
          ▼
    Web Search
          │
          ▼
 Product & Price Data
          │
          ▼
    AI Analysis
          │
          ▼
 ┌───────────────────┐
 │ BUY / WAIT / SKIP │
 └───────────────────┘
          │
          ▼
 Sellers + Alternatives
```

---

## 🛠️ Tech Stack

* **Python**
* **Streamlit** — Web interface
* **OpenAI API** — AI-powered analysis
* **Web Search** — Product, seller, and pricing research

---

## 📋 Requirements

Before running the project, make sure you have:

* Python 3.9+
* An OpenAI API key
* Internet access

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd <PROJECT_DIRECTORY>
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure your OpenAI API key

#### macOS / Linux

```bash
export OPENAI_API_KEY="sk-..."
```

#### Windows Command Prompt

```cmd
set OPENAI_API_KEY=sk-...
```

#### Windows PowerShell

```powershell
$env:OPENAI_API_KEY="sk-..."
```

> **Security:** Never commit your API key to GitHub or include it directly in your source code.

---

## ▶️ Run the Application

Start the Streamlit application with:

```bash
streamlit run app.py
```

Streamlit will provide a local URL where you can access the application.

---

## 🎯 How to Use

1. Open the application.
2. Enter a **product name** or **product URL**.
3. Choose the AI model from the sidebar if needed.
4. Set the **Max Web Searches** limit.
5. Run the price check.
6. Review the:

   * BUY / WAIT / SKIP verdict
   * Product information
   * Available sellers
   * Pricing information
   * Recommended alternatives

---

## 💰 Cost Control

Web searches and AI requests can generate API costs, so the application includes controls to help manage usage.

### Max Web Searches

The **Max Web Searches** slider limits the number of web searches performed during each product check.

> Each web search may incur a cost depending on the configured search/API provider.

For quick testing, try setting:

```text
Max Web Searches: 3
```

### OpenAI Model

The default model is:

```text
gpt-5-mini
```

You can change the model from the application's sidebar when other supported models are available.

### Monthly Budget

For additional protection against unexpected API usage, configure a **monthly spending limit** in your OpenAI dashboard.

---

## 🎥 Demo Tips

For a good demonstration, test the application with **2–3 different products** representing different scenarios.

### Example scenarios

**1. Good Deal**

Choose a product whose current price is attractive compared with similar listings.

Expected result:

```text
BUY
```

**2. Overpriced Product**

Choose a product that is significantly more expensive than comparable alternatives.

Expected result:

```text
SKIP
```

**3. Upcoming/New Model**

Choose an older product where a newer model is expected or recently released.

Expected result:

```text
WAIT
```

### Recommended Demo Settings

For a fast demonstration:

```text
Max Web Searches: 3
```

This keeps the response relatively quick while still allowing the agent to gather useful information.

---

## 📁 Project Structure

```text
Price-Check-Sidekick/
│
├── app.py
├── requirements.txt
├── README.md
│
└── ...
```

Additional files and modules may be added as the project evolves.

---

## 🔐 Environment Variables

The application expects the following environment variable:

| Variable         | Description                            |
| ---------------- | -------------------------------------- |
| `OPENAI_API_KEY` | API key used to access OpenAI services |

Example:

```bash
OPENAI_API_KEY=sk-...
```

For local development, consider using a `.env` file or your operating system's environment-variable configuration rather than hard-coding credentials.

---

## ⚠️ Disclaimer

Price-Check Sidekick provides AI-generated recommendations based on information retrieved from the web.

Prices, availability, seller information, and product specifications can change at any time. Always verify the final price, seller, product specifications, warranty, shipping costs, and return policy before purchasing.

The **BUY / WAIT / SKIP** result should be treated as an informational recommendation, not a guarantee of product value.

---

## 🔮 Future Improvements

Potential future enhancements include:

* 📈 Historical price tracking
* 🔔 Price-drop alerts
* 📊 Price history charts
* 🏪 More retailer integrations
* 🌎 Region-specific pricing
* 💵 Currency conversion
* ⭐ Seller reliability scoring
* 📦 Shipping-cost comparison
* 🧾 Product review analysis
* 💬 Conversational shopping assistant
* 🗂️ Saved products and watchlist

---

## 👨‍💻 Author

**Mukit**

Built with Python, Streamlit, web search, and OpenAI.
