// Confirm before risky forms (e.g. delete)
document.querySelectorAll("form[data-confirm]").forEach(function (f) {
  f.addEventListener("submit", function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
});
// Quiz: live "x of N answered" counter and warning for unanswered questions
var quiz = document.getElementById("quizForm");
if (quiz) {
  var total = parseInt(quiz.dataset.total) || quiz.querySelectorAll("input[name=qid]").length;
  var count = function () { return quiz.querySelectorAll("input[type=radio]:checked").length; };
  quiz.addEventListener("change", function () {
    document.getElementById("answered").textContent = count() + " of " + total + " answered";
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

// Note filter toggle (expand / collapse)
var noteToggle = document.getElementById("noteFilterToggle");
var noteBody = document.getElementById("noteFilterBody");
var toggleArrow = document.getElementById("toggleArrow");
if (noteToggle && noteBody) {
  noteToggle.addEventListener("click", function () {
    noteBody.classList.toggle("open");
    toggleArrow.classList.toggle("open");
  });
}

// Note filter: select all / clear all
var selectAll = document.getElementById("selectAllNotes");
var clearAll = document.getElementById("clearAllNotes");
if (selectAll) {
  selectAll.addEventListener("click", function () {
    document.querySelectorAll(".note-checkboxes input[type=checkbox]").forEach(function (cb) { cb.checked = true; });
    updateNoteCount();
  });
}
if (clearAll) {
  clearAll.addEventListener("click", function () {
    document.querySelectorAll(".note-checkboxes input[type=checkbox]").forEach(function (cb) { cb.checked = false; });
    updateNoteCount();
  });
}

// Update the "x selected" counter in the header
function updateNoteCount() {
  var header = document.querySelector(".note-selector-header .muted");
  if (!header) return;
  var all = document.querySelectorAll(".note-checkboxes input[type=checkbox]");
  var checked = document.querySelectorAll(".note-checkboxes input[type=checkbox]:checked");
  if (checked.length === 0) {
    header.textContent = "(none selected)";
  } else if (checked.length === all.length) {
    header.textContent = "(using all notes)";
  } else {
    header.textContent = "(" + checked.length + " of " + all.length + " selected)";
  }
}
document.querySelectorAll(".note-checkboxes input[type=checkbox]").forEach(function (cb) {
  cb.addEventListener("change", updateNoteCount);
});
