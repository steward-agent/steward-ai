(function () {
  function key() {
    if (window.crypto && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return "idem-" + Date.now().toString(16) + Math.random().toString(16).slice(2);
  }

  function mount(options) {
    const config = options || {};
    const host = document.createElement("div");
    host.setAttribute("data-ecommerce-agent", "widget");
    document.body.appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = [
      "<style>",
      ":host { all: initial; }",
      ".launcher { position: fixed; right: 1.25rem; bottom: 1.25rem; z-index: 2147483000;",
      "background: #1f4d3a; color: #f7f4ee; border: 0; border-radius: 999px;",
      "padding: 0.8rem 1.1rem; font: 600 0.95rem/1 sans-serif; cursor: pointer; }",
      ".panel { position: fixed; right: 1.25rem; bottom: 4.5rem; z-index: 2147483000;",
      "width: min(24rem, calc(100vw - 2rem)); height: 32rem; max-height: calc(100vh - 6rem);",
      "display: none; flex-direction: column; background: #fffdf8; color: #1c1915;",
      "border: 1px solid #d9d1c3; border-radius: 1rem; box-shadow: 0 16px 40px rgba(40, 30, 10, 0.16); }",
      ".panel.open { display: flex; }",
      "header { padding: 1rem 1rem 0.5rem; }",
      "h2 { margin: 0; font: 600 1.15rem/1.2 Georgia, serif; }",
      ".note { margin: 0.35rem 0 0; color: #5c564c; font: 0.8rem/1.4 sans-serif; }",
      ".log { flex: 1; overflow: auto; padding: 0.5rem 1rem; display: flex; flex-direction: column; gap: 0.5rem; }",
      ".bubble { margin: 0; padding: 0.65rem 0.75rem; border-radius: 0.75rem; font: 0.92rem/1.4 sans-serif; white-space: pre-wrap; }",
      ".shopper { align-self: flex-end; background: #1f4d3a; color: #f7f4ee; max-width: 85%; }",
      ".agent { align-self: flex-start; background: #f3eee4; max-width: 90%; }",
      ".prompts { display: flex; flex-wrap: wrap; gap: 0.4rem; padding: 0 1rem 0.5rem; }",
      ".prompts button, form button { background: #fff; border: 1px solid #cfc6b8; border-radius: 999px;",
      "padding: 0.35rem 0.7rem; font: 0.78rem/1.2 sans-serif; cursor: pointer; color: #1c1915; }",
      "form { display: flex; gap: 0.4rem; padding: 0.75rem; border-top: 1px solid #eee6da; }",
      "textarea { flex: 1; resize: none; border: 1px solid #cfc6b8; border-radius: 0.7rem; padding: 0.55rem;",
      "font: 0.92rem/1.3 sans-serif; }",
      "form button { border-radius: 0.7rem; background: #1f4d3a; color: #f7f4ee; border: 0; padding: 0 0.9rem; }",
      "</style>",
      '<button class="launcher" type="button">Support</button>',
      '<section class="panel" role="dialog" aria-label="Store support">',
      "<header><h2>Store support</h2>",
      '<p class="note">Refunds and questions for this store. Do not type card numbers. Payments stay with the store\'s payment provider.</p></header>',
      '<div class="log" aria-live="polite"></div>',
      '<div class="prompts"></div>',
      '<form><textarea rows="2" maxlength="4000" aria-label="Message" placeholder="Ask about an order"></textarea>',
      '<button type="submit">Send</button></form>',
      "</section>"
    ].join("");

    const launcher = shadow.querySelector(".launcher");
    const panel = shadow.querySelector(".panel");
    const log = shadow.querySelector(".log");
    const form = shadow.querySelector("form");
    const input = shadow.querySelector("textarea");
    const prompts = shadow.querySelector(".prompts");
    const suggestions = [
      "I want to return my headphones",
      "What is your return policy?",
      "Quote 80 USD in EUR"
    ];
    suggestions.forEach(function (text) {
      const prompt = document.createElement("button");
      prompt.type = "button";
      prompt.textContent = text;
      prompt.addEventListener("click", function () {
        submit(text);
      });
      prompts.appendChild(prompt);
    });

    function add(text, role) {
      const item = document.createElement("p");
      item.className = "bubble " + role;
      item.textContent = text;
      log.appendChild(item);
      log.scrollTop = log.scrollHeight;
    }

    async function submit(text) {
      const message = text.trim();
      if (!message) {
        return;
      }
      add(message, "shopper");
      input.value = "";
      try {
        const response = await fetch((config.endpoint || "") + "/v1/messages", {
          method: "POST",
          headers: {
            Authorization: "Bearer " + config.publicToken,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            message: message,
            channel: "web",
            customer_ref: config.customerRef || null,
            order_id: config.orderId || null,
            customer_signature: config.customerSignature || null,
            customer_expires: config.customerExpires || null,
            idempotency_key: key()
          })
        });
        const payload = await response.json();
        add(payload.message || payload.error || "The support service did not answer.", "agent");
      } catch (error) {
        add("The support service did not respond. Your payment provider was not charged by this widget.", "agent");
      }
    }

    launcher.addEventListener("click", function () {
      const open = panel.classList.toggle("open");
      launcher.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        input.focus();
      }
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      submit(input.value);
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit(input.value);
      }
    });
    shadow.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        panel.classList.remove("open");
      }
    });
  }

  window.EcommerceAgent = { mount: mount };
})();
