# Refund policy

You can return headphones and request a refund within 30 days of delivery. The refund goes back through the payment provider that took the original payment. This sample is for a local demo. Replace it with your store's refund policy.

```rules
return_window_days: 30
partial_refunds: yes
non_refundable: gift card, digital download, final sale
support_alert_above: 50.00
```

The agent checks these rules before it asks the payment provider for a refund:

- The signed-in customer must match the order.
- The refund currency must match the order currency.
- The amount must be greater than zero and no more than the refundable balance.
- The order must be inside the return window. The stricter of this policy and RETURN_WINDOW_DAYS applies.
- A refund above the support line alerts support and waits. No money moves until support approves it.
- Gift cards, digital downloads, and items marked final sale are non-refundable.
- A partial refund is allowed only when partial_refunds is yes. A full refund of the remaining balance is the default request.
