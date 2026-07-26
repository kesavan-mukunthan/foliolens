(function () {
  "use strict";

  function compareCells(aRaw, bRaw, dir) {
    var an = parseFloat(aRaw);
    var bn = parseFloat(bRaw);
    var aIsNum = aRaw !== "" && !isNaN(an);
    var bIsNum = bRaw !== "" && !isNaN(bn);
    if (aIsNum && bIsNum) {
      return dir === "asc" ? an - bn : bn - an;
    }
    if (aIsNum !== bIsNum) {
      return aIsNum ? -1 : 1;
    }
    var cmp = String(aRaw).localeCompare(String(bRaw));
    return dir === "asc" ? cmp : -cmp;
  }

  function sortTable(table, colIndex, dir) {
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var av = a.cells[colIndex].getAttribute("data-value");
      var bv = b.cells[colIndex].getAttribute("data-value");
      return compareCells(av, bv, dir);
    });
    rows.forEach(function (row) {
      tbody.appendChild(row);
    });
  }

  function initSortableTable(table) {
    var headers = table.tHead.rows[0].cells;
    for (var i = 0; i < headers.length; i++) {
      (function (colIndex, th) {
        if (th.getAttribute("data-sortable") !== "true") return;
        th.addEventListener("click", function () {
          var dir = th.getAttribute("data-dir") === "asc" ? "desc" : "asc";
          for (var j = 0; j < headers.length; j++) {
            headers[j].removeAttribute("data-dir");
          }
          th.setAttribute("data-dir", dir);
          sortTable(table, colIndex, dir);
        });
      })(i, headers[i]);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var tables = document.querySelectorAll("table[data-sortable-table]");
    for (var i = 0; i < tables.length; i++) {
      initSortableTable(tables[i]);
    }
  });
})();
