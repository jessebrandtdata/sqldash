import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";

// Appends the served theme after the app's own stylesheet; a failed load changes nothing.
const theme = document.createElement("link");
theme.rel = "stylesheet";
theme.href = "theme.css";
document.head.appendChild(theme);

mount(App, { target: document.getElementById("app") });
