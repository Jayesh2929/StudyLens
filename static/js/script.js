// Confirm before risky forms (e.g. delete)
document.querySelectorAll("form[data-confirm]").forEach(function (f) {
  f.addEventListener("submit", function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
});
// Quiz: live "x of 5 answered" counter and warning for unanswered questions
var quiz = document.getElementById("quizForm");
if (quiz) {
  var total = quiz.querySelectorAll("input[name=qid]").length;
  var count = function () { return quiz.querySelectorAll("input[type=radio]:checked").length; };
  quiz.addEventListener("change", function () {
    document.getElementById("answered").textContent = count() + " of " + total + " answered";
    document.getElementById("qfill").style.width = (count() / total * 100) + "%";
  });
  quiz.addEventListener("submit", function (e) {
    var left = total - count();
    if (left > 0 && !confirm(left + " question(s) unanswered. Submit anyway?")) e.preventDefault();
  });
}
// Upload: drag and drop a file onto the drop zone
var zone = document.querySelector(".dropzone");
if (zone) {
  var input = zone.querySelector("input[type=file]");
  ["dragenter", "dragover"].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.add("over"); }); });
  ["dragleave", "drop"].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.remove("over"); }); });
  zone.addEventListener("drop", function (e) { if (e.dataTransfer.files.length) input.files = e.dataTransfer.files; });
}
// Hide messages after 5 seconds
setTimeout(function () { document.querySelectorAll(".alert").forEach(function (a) { a.style.display = "none"; }); }, 5000);

// Note picker: "Select all" / "Clear" buttons
document.querySelectorAll("[data-pick]").forEach(function (b) {
  b.addEventListener("click", function () {
    b.closest(".picker").querySelectorAll("input[type=checkbox]").forEach(function (c) { c.checked = b.dataset.pick === "all"; });
  });
});
