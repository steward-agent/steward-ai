# Steward — product website brief

This website explains the agent. It is not a store, not a product grid, and not a checkout. A merchant reads it to understand what the agent does on their existing shop.

The agent is an open-source plugin a store adds to its own website. It answers shoppers, starts returns, and asks the payment provider the store already uses to move money. The agent does not take cards and does not hold funds.

## Navigation

The same bar on every page:

- Overview
- About
- GitHub
- Contact

Overview is the landing page. GitHub opens the open-source repository.

## Who it is for

A merchant, a store operator, or a developer deciding whether to install the plugin.

## Tone

Calm and specific. Short sentences. No AI slogans. No claim that the agent stores money or card numbers.

## Colors

| Use | Hex |
| --- | --- |
| Page background | `#F4F1EA` |
| Panel and card background | `#FFFDF8` |
| Text | `#1C1915` |
| Secondary text | `#5C564C` |
| Green, buttons and shopper messages | `#1F4D3A` |
| Text on green | `#F7F4EE` |
| Agent message background | `#F3EEE4` |
| Borders | `#D9D1C3` |
| Soft dividers | `#EEE6DA` |
| Waiting for support | `#8A5A12` on `#F6EAD4` |
| Refund sent | `#1F4D3A` on `#E5EFE9` |
| Not refunded | `#8C3A32` on `#F6E6E3` |

## Pages

Design these four pages. Desktop and a 390px-wide phone for each.

1. Overview, the landing page, with a demo
2. About
3. GitHub, open source
4. Contact

---

## 1. Overview

The landing page. The demo sits on this page, under the introduction.

**Name:** Steward

**One line:** A support agent for your store. It answers questions, starts returns, and uses the payment system you already have.

**Three points:**

- Answers from your rules and FAQs
- Starts a refund only when your rules allow it
- Sends the money through Stripe, Paystack, Flutterwave, Shopify, or any other provider you connect

**Demo**

Label the block **Demo**. It shows the agent at work. It is not a shop.

A support panel with one finished conversation:

- Shopper: I want to return my headphones
- Agent: The return for Headphones on order 1001 is waiting for support. Support was alerted because the refund of 80.00 USD is above 50.00 USD. No refund was sent to the payment provider.

Status on the reply: **Waiting for support**

One line under the panel: This is a sample. The store’s own rules decide the amount that alerts support. The sample amount is 50.00 in the order currency.

**Button under the demo:** Read about the agent

**Footer:** Open source. You run it beside your store. Your payment keys stay on your server.

---

## 2. About

Title: About the agent

Four blocks. Each block is a heading, two sentences, and one example line.

**Customer questions**

The agent answers from the refund rules, payment rules, and FAQs the store added.

Example: You can request a refund within 30 days. The refund goes back through the original payment provider.

**Returns and refunds**

The agent checks the signed-in customer, the currency, the refundable balance, the return window, and whether the item can be returned. The store’s commerce system records the return. The store’s payment provider sends the refund.

Example: Headphones, 40.00 USD, inside the rules. The agent records the return and sends the refund.

**Support alert**

A refund above 50.00 in the order currency alerts the store’s support team and waits. The store can change that amount.

Example: The return for Headphones on order 1001 is waiting for support. No refund was sent.

**Currency quote**

The agent asks the store’s payment provider for a quote. The quote is not a completed payment.

Example: 80.00 USD is quoted as 73.60 EUR. This is not a completed payment.

A smaller note: Settlement, the report of what the provider has captured or paid out, runs from the store’s backend.

**Rules the agent reads**

Three cards:

- Refund policy. 30 days. Partial refunds allowed. Gift cards, digital downloads, and final sale are excluded. Support is alerted above 50.00.
- Payment policy. Quotes come from the connected provider. A quote is not a payment. Card numbers stay at the provider’s checkout.
- FAQs. How long a return takes, where the refund goes, and what happens above 50.00.

Line under the cards: The store replaces these with its own files. The agent then reads the store’s version.

**Providers**

- Stripe. Secret key and publishable key.
- Paystack. Secret key and public key.
- Flutterwave. Secret key and public key.
- Shopify. Admin token.
- Any other provider the store already uses.

The page lists the names of the keys. It does not show a key, and it has no field where a visitor pastes one.

---

## 3. GitHub

Title: Open source

One sentence: The agent is open source under the MIT license. You run it beside your own store.

Three points:

- The code is on GitHub.
- A store connects the payment provider it already uses.
- Payment keys stay on the store’s server. They are not in the repository.

**Button:** View on GitHub

The button is the only path to the repository. Do not invent a star count.

---

## 4. Contact

Title: Contact

One sentence: Ask about adding the agent to your store.

Fields:

- Name
- Work email
- Message
- Button: Send

A short note under the form: Do not send card numbers or payment keys.

---

## What every screen must leave out

- A shop grid, a cart, or a checkout
- Card number, expiry, or security code fields
- Bank account fields
- A visible secret key
- A balance held by the agent

## Suggested delivery

One desktop frame and one phone frame for each of the four pages. The Overview frames include the demo.
