/* ===========================================================================
   Social Media BOT - interface behaviour

   Deliberately small and dependency-free: no framework, no build step, no CDN.
   Three jobs:
     1. confirm destructive actions before they are submitted;
     2. refresh the upload queue's progress bars without a page reload;
     3. keep the "convert to Shorts" hint honest on the upload form.
   =========================================================================== */

(function () {
    "use strict";

    /* ---------------------------------------------------------------------
       1. Confirmation for destructive buttons.
       Any element carrying data-confirm="..." asks before submitting.
       --------------------------------------------------------------------- */
    function wireConfirmations() {
        document.querySelectorAll("[data-confirm]").forEach(function (element) {
            element.addEventListener("click", function (event) {
                if (!window.confirm(element.getAttribute("data-confirm"))) {
                    event.preventDefault();
                }
            });
        });
    }

    /* ---------------------------------------------------------------------
       2. Live upload queue.
       Present only on pages with #queue-live. Polls the JSON API and updates
       the progress bar and status cell in place. Stops polling when the queue
       empties, so an idle dashboard makes no requests at all.
       --------------------------------------------------------------------- */
    var POLL_INTERVAL_MS = 5000;
    var pollTimer = null;

    function updateQueue() {
        fetch("/api/queue", { credentials: "same-origin" })
            .then(function (response) {
                if (!response.ok) { throw new Error("queue request failed"); }
                return response.json();
            })
            .then(function (data) {
                var active = 0;
                data.jobs.forEach(function (job) {
                    var row = document.querySelector('[data-job-id="' + job.id + '"]');
                    if (!row) { return; }
                    active += 1;

                    var bar = row.querySelector(".progress-bar");
                    if (bar) { bar.style.width = job.progress + "%"; }

                    var statusCell = row.querySelector("[data-job-status]");
                    if (statusCell && statusCell.textContent.trim() !== job.status) {
                        statusCell.textContent = job.status;
                    }

                    var percentCell = row.querySelector("[data-job-percent]");
                    if (percentCell) { percentCell.textContent = job.progress + "%"; }
                });

                // Nothing left to watch: a status changed to a terminal one, so
                // reload once to pick up the final result, then stop.
                if (active === 0 && pollTimer !== null) {
                    window.clearInterval(pollTimer);
                    pollTimer = null;
                    window.location.reload();
                }
            })
            .catch(function () {
                /* A transient network error is not worth interrupting the page
                   for - the next tick will try again. */
            });
    }

    function wireQueuePolling() {
        var container = document.getElementById("queue-live");
        if (!container) { return; }
        if (!container.querySelector("[data-job-id]")) { return; }
        pollTimer = window.setInterval(updateQueue, POLL_INTERVAL_MS);
    }

    /* ---------------------------------------------------------------------
       3. Upload form: warn when a chosen file is very large, since the
       conversion happens during the request.
       --------------------------------------------------------------------- */
    var LARGE_FILE_MB = 500;

    function wireUploadHint() {
        var input = document.querySelector('input[type="file"][name="video_file"]');
        var hint = document.getElementById("upload-hint");
        if (!input || !hint) { return; }

        input.addEventListener("change", function () {
            if (!input.files || !input.files.length) {
                hint.textContent = "";
                return;
            }
            var sizeMb = input.files[0].size / (1024 * 1024);
            hint.textContent =
                "Selected " + sizeMb.toFixed(1) + " MB." +
                (sizeMb > LARGE_FILE_MB
                    ? " Large files take a while to upload and convert - keep this tab open."
                    : "");
        });
    }

    /* --------------------------------------------------------------------- */
    document.addEventListener("DOMContentLoaded", function () {
        wireConfirmations();
        wireQueuePolling();
        wireUploadHint();
    });
})();
