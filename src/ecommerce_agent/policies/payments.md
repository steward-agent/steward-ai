# Payment policy

Currency conversion quotes come from the payment provider connected to this store. Settlement reports show what that provider has captured or paid out. This plugin does not hold funds and does not store card numbers.

```rules
currency_conversion: yes
accepted_currencies: USD, EUR, GBP, NGN
```

The agent checks these payment rules before it quotes a conversion or sends a refund:

- Currency conversion is offered only when currency_conversion is yes.
- A quote is indicative. It is not a completed payment, and card confirmation stays in the provider checkout.
- A currency outside accepted_currencies is refused for refunds and for quotes.
- Card numbers are never stored or forwarded.
- Settlement and capture run only from the store backend.
