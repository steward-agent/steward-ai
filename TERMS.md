# Terms and Conditions

These terms cover use of the Ecommerce Agent software. The [MIT License](LICENSE) covers copyright. These terms cover how a store may run the software against payments, refunds, settlement, and customer conversations.

This document is not legal advice. Have your own counsel review it before you use the software in production.

Plain summary: you connect the payment provider and commerce system you already use. You keep cardholder data and provider secrets in your systems. You set the refund rules. Contributors do not operate a payment account for you and do not receive your customers' payment data.

## 1. Agreement

By running, embedding, or modifying this software for a store, you agree to these terms. If you do not agree, do not use it with live payments.

## 2. The software

Ecommerce Agent is a workflow plugin. It routes a shopper request, checks the rules you configure, and calls the commerce and payment plugins you select. You host it. One deployment is for one merchant.

## 3. Your payment systems

You connect the payment provider, acquirer, and commerce platform you already have. Those providers move and hold funds. You supply their credentials through environment variables on your server, or through an adapter you operate.

You are the merchant of record for your sales, or you have the authority of that merchant. You keep the agreements, keys, and compliance duties those providers require, including PCI DSS scope, tax, consumer refund rights, and sanctions screening where they apply to you.

## 4. Data you keep

You decide where orders, customers, and policies live. This software reads them through your plugins for the duration of a request.

You keep provider secret keys, access tokens, and bank credentials in your environment or secret manager. You do not put them in the widget, in git, or in a prompt.

You do not send card numbers, card verification values, or bank account numbers to this plugin. Your checkout sends card data to your payment provider. If a shopper pastes a card number into the widget, the plugin redacts it and does not forward it to a model or a tool.

Conversation text is handled in memory for that request. The plugin does not ship a database of shopper messages. If you want a transcript, you store it in your own systems under your privacy notice.

## 5. Approval and refunds

You choose the approval plugin, the auto-approve limit, and the support alert line. A refund above that line notifies your support channel and waits. A refund, capture, or converted payment is sent only through your payment plugin after those rules pass.

You are responsible for the limit you set, the policy documents you load, and the approval webhook you expose. An approval webhook that returns `approved` is your instruction to send the refund through your provider.

You send a stable idempotency key for money movement. Your provider must honor that key so a retry does not create a second refund.

## 6. The website plugin

The public token identifies the widget. The server token stays on your backend. You sign short-lived grants for a customer id and an order id after your store has authenticated that shopper. You do not put the server token in a page, a mobile app, or a public repository.

## 7. Acceptable use

You use the software for your own store's customer service, returns, settlement reconciliation, and payment conversion through your providers.

You do not use it to move money for unrelated third parties, to store card data, to bypass your payment provider's controls, or to hide who the merchant is.

## 8. Your customers

You present your own terms, return window, and privacy notice to your shoppers. The sample policy files in this repository are demos. You replace them with your policy.

You are responsible for the answers the plugin gives from the documents you supplied, and for reviewing the auto-approve limit before you enable it.

## 9. Open source and contributions

The software is licensed under the MIT License. These terms do not change that license. Contributions are accepted under the MIT License, as described in [CONTRIBUTING.md](CONTRIBUTING.md). There is no contributor license agreement.

## 10. Warranty and liability

The MIT License warranty and liability terms apply to the software. Contributors do not warrant that a refund, quote, settlement report, or customer answer will be correct, complete, or available. Contributors are not a party to the payment between you, your shopper, and your payment provider.

To the maximum extent permitted by law, contributors are not liable for lost funds, failed refunds, provider fees, lost profits, or data you chose to send to a model or a webhook. You carry the risk of the payment flows you enable.

## 11. Changes

The terms shipped with a release apply to that release. Later changes apply to later releases. The MIT License continues to apply to the code you already received.

## 12. Contact

Questions about these terms can be opened as an issue on the project repository. Security reports follow [SECURITY.md](SECURITY.md).
