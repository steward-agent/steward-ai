# GDPR and similar privacy laws

Public guidance for merchants who run Ecommerce Agent in the EEA, UK, or other regions with comparable rules. This is not legal advice and does not create a data processing agreement with project maintainers.

## Lawful basis (merchant)

The store decides the lawful basis for processing shopper data in its privacy notice. Typical bases for support and returns include contract performance and legitimate interests in handling a return the shopper requested. Marketing is out of scope for this plugin.

## Data subject rights

Shoppers exercise rights with the store, not with the open-source maintainers.

| Right | How it maps here |
| --- | --- |
| Access / portability | Export order and support records from the store's systems |
| Rectification | Correct customer and order data in the commerce platform |
| Erasure | Delete or anonymize transcripts and profiles the store kept |
| Restriction / objection | Pause automated refunds or support routing in the store's configuration |
| Complaint | Lodge with the store and, where applicable, a supervisory authority |

## Processors the merchant chooses

Payment, commerce, approval, support-alert, and optional observability exporters are processors or separate controllers under the merchant's contracts. Configure only providers the store has reviewed.

## Special category and payment data

Do not send health, biometric, or other special-category data through the widget. Cardholder data stays with the payment provider. The agent redacts card numbers, CVV, emails, and secret tokens from free text.

## Records of processing

The merchant keeps its own record of processing activities. This repository documents technical controls in [DATA_PROTECTION.md](DATA_PROTECTION.md), [PII.md](PII.md), and [SECURITY.md](SECURITY.md).

## Breach notification

If a merchant deployment leaks tokens or shopper data, the merchant follows its incident process and applicable notification rules. Report vulnerabilities in this code under [SECURITY.md](SECURITY.md).

## Children

The software is for store operators and signed-in shoppers as defined by the store. Do not use it to collect data from children without the store's lawful basis and parental controls.
