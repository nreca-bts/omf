function updateFileNameDisplay(fileInputID, userFileDisplayNameID, dataFileNameID) {
	// Used with the direct file upload handler.
	var fileInput = document.getElementById(fileInputID);
	var displayInput = document.getElementById(userFileDisplayNameID);

	if ( fileInput.files.length > 0 ) {
			displayInput.value = fileInput.files[0].name;
	}
}

function getCsrfToken() {
	// Read the CSRF token from a same-origin cookie set by the server.
	if (typeof window !== 'undefined' && window.CSRF_TOKEN) {
		return window.CSRF_TOKEN
	}
	var cookieName = '_csrf_token='
	var cookies = document.cookie ? document.cookie.split(';') : []
	for (var i = 0; i < cookies.length; i++) {
		var cookie = cookies[i].trim()
		if (cookie.indexOf(cookieName) === 0) {
			return decodeURIComponent(cookie.substring(cookieName.length))
		}
	}
	return ''
}

function ensureFormHasCsrfToken(form) {
	// Ensure normal HTML POST forms submit the CSRF token.
	if (!form || !form.getAttribute) {
		return
	}
	var method = (form.getAttribute('method') || form.method || '').toLowerCase()
	if (method !== 'post') {
		return
	}
	var token = getCsrfToken()
	if (!token) {
		return
	}
	var existingField = form.querySelector("input[name='_csrf_token']")
	if (!existingField) {
		existingField = document.createElement('input')
		existingField.setAttribute('type', 'hidden')
		existingField.setAttribute('name', '_csrf_token')
		form.appendChild(existingField)
	}
	existingField.setAttribute('value', token)
}

function initializeCsrfProtection() {
	// Add CSRF protection to all regular POST forms and jQuery AJAX calls.
	if (typeof document === 'undefined') {
		return
	}
	Array.prototype.forEach.call(document.getElementsByTagName('form'), ensureFormHasCsrfToken)
	if (!window.__omfCsrfFormHookRegistered) {
		document.addEventListener('submit', function(event) {
			ensureFormHasCsrfToken(event.target)
		}, true)
		window.__omfCsrfFormHookRegistered = true
	}
	if (window.jQuery && !window.__omfCsrfAjaxSetup) {
		window.jQuery.ajaxSetup({
			beforeSend: function(xhr, settings) {
				var method = String((settings && (settings.type || settings.method)) || 'GET').toUpperCase()
				if (!/^(GET|HEAD|OPTIONS|TRACE)$/.test(method)) {
					var token = getCsrfToken()
					if (token) {
						xhr.setRequestHeader('X-CSRFToken', token)
					}
				}
			}
		})
		window.__omfCsrfAjaxSetup = true
	}
}

if (document.readyState === 'loading') {
	document.addEventListener('DOMContentLoaded', initializeCsrfProtection)
} else {
	initializeCsrfProtection()
}

function handle_files(files, contentsId, nameId) {
	// Helper function to pull file contents in to an allInputData data structure.
	// Read the file
	reader = new FileReader()
	reader.readAsText(files[0])
	// After loading, put the name and content in the right hidden inputs:
	reader.onload = function loaded(evt) {
		document.getElementById(nameId).value = files[0].name
		document.getElementById(contentsId).value = reader.result
	}
}

function gebi(id) {
	// Shorten a much-used method name:
	return document.getElementById(id)
}

function time(func) {
	// How long does func take to execute?
	// Todo: move into microgridPlan.html
	var start = +new Date()
	func()
	var end =  +new Date()
	return end - start
}

function round(number,precision) {
	// Simple rounding function used a couple different places.
	return parseFloat(number.toPrecision(precision))
}

function dropPill(thisButton, name) {
	// Drop down a pill menu, used on home, transEdit, etc.
	thisButton.style.color= 'black'
	thisButton.style.background= '#F8F8F8'
	thisButton.style.textAlign = 'left'
	thisButton.nextSibling.nextSibling.style.display = 'inline-block'
	thisButton.innerHTML = name + ' ▴'
	function clickCloseEvent() {
		thisButton.nextSibling.nextSibling.style.display = 'none'
		thisButton.innerHTML = name + ' ▾'
		this.removeEventListener('click', arguments.callee, true)
		thisButton.style.color= 'white'
		thisButton.style.background= 'transparent'
		if (window.event.toElement==thisButton) {event.stopPropagation()}
	}
	document.body.addEventListener('click', clickCloseEvent, true)
}
function clickCloseEvent(labelName, buttonName) {
	// close handler for dropdown menus on home, transEdit, etc.
	var thisButton = document.getElementById(buttonName);
	thisButton.nextSibling.nextSibling.style.display = 'none'
	thisButton.innerHTML = labelName + ' ▾'
	this.removeEventListener('click', arguments.callee, true)
	if (window.event.toElement==thisButton) {event.stopPropagation()}
}

function delimitNumbers(nStr) {
	// Add commas to numbers and round to a decent length.
	nStr += ''
	x = nStr.split('.')
	x1 = x[0]
	x2 = x.length > 1 ? '.' + x[1] : ''
	rgx = /(\d+)(\d{3})/
	while (rgx.test(x1)) {
		x1 = x1.replace(rgx, '$1' + ',' + '$2')
	}
	return x1 + x2
}

function post_to_url(path, params, method) {
	// helper function for cancelModel, deleteModel, shareModel, duplicateModel, createModelName.
	method = method || 'post' // Set method to post by default, if not specified.
	params = params || {}
	if (String(method).toUpperCase() === 'POST' && !params.hasOwnProperty('_csrf_token')) {
		params._csrf_token = getCsrfToken()
	}
	var form = document.createElement('form')
	form.setAttribute('method', method)
	form.setAttribute('action', path)
	for(var key in params) {
		if(params.hasOwnProperty(key)) {
			var hiddenField = document.createElement('input')
			hiddenField.setAttribute('type', 'hidden')
			hiddenField.setAttribute('name', key)
			hiddenField.setAttribute('value', params[key])
			form.appendChild(hiddenField)
		}
	}
	document.body.appendChild(form)
	form.submit()
}

function cancelModel() {
	// Cancels model execution via the button on each model page.
	params = {user:allInputData.user,
		modelName:allInputData.modelName,
		modelType:allInputData.modelType}
	post_to_url("/cancelModel/", params, "POST")
}

function deleteModel() {
	// Warn before deleting when user hits delete button on model.
	if (confirm("Deleting this model cannot be undone. Continue?")){
		post_to_url("/delete/Model/"+allInputData.user+"/"+allInputData.modelName, {}, "POST")
	} else {
		return false
	}
}

function shareModel() {
	// Display dialog and handle user inputs for the share model button.
	const viewers = allInputData.viewers == null ? [] : allInputData.viewers;
	const modal = document.createElement("div");
	modal.id = "emailModal";
	const modalContent = document.createElement("div");
	modalContent.id = "emailModalContent";
	modal.append(modalContent);
	// Add title and instructions
	const h = document.createElement("h1");
	h.textContent = "Share";
	modalContent.append(h);
	const p = document.createElement("p");
	p.textContent = "As the model owner, you may view, duplicate, run, share, and delete this model. " + 
		"Users that you choose to share with may only view and duplicate this model.";
	modalContent.append(p);
	const privacyIndicator = document.createElement("p");
	if (viewers.length === 0) {
		privacyIndicator.textContent = "The model is currently private."
	} else {
		privacyIndicator.textContent = "The model is currently shared."
	}
	modalContent.append(privacyIndicator);
	// Create form and table
	const form = document.createElement("form");
	modalContent.append(form);
	const div = document.createElement("div");
	div.classList.add("tableContainer");
	form.append(div);
	
	const table = document.createElement("table");
	div.append(table);
	const tbody = document.createElement("tbody");
	table.append(tbody);
	for (const email of viewers) {
		const row = getEmailRow()
		row.querySelector("input[name='email']").value = email;
		tbody.append(row);
	}
	// Add add button
	const addButton = getAddButton();
	form.append(addButton);
	// Add buttons
	const buttonDiv = document.createElement("div");
	buttonDiv.classList.add("buttonDiv");
	form.append(buttonDiv);
	const submitButton = getSubmitButton();
	buttonDiv.append(submitButton);
	const closeButton = getCloseButton();
	buttonDiv.append(closeButton);
	form.addEventListener("submit", e => {
		e.preventDefault();
		submitButton.disabled = true;
		const formData = new FormData(form);
		formData.set("user", allInputData.user);
		formData.set("modelName", allInputData.modelName);
		$.ajax({
			type: "POST",
			url: "/shareModel",
			data: formData,
			processData: false,
			contentType: false
		}).done(function(data, text, jqXHR) {
			const emails = JSON.parse(jqXHR.responseText);
			allInputData.viewers = emails;
			closeButton.click();
			shareModel();
			alert("Successfully updated your selection of shared users.");
		}).fail(function(jqXHR, textStatus, errorThrown) {
			resetInvalidFlags();
			if (jqXHR.status === 409) {
				alert(jqXHR.responseText);
			} else if (jqXHR.status === 400) {
				try {
					// Blocked emails (self-share, admin) — mark specific inputs
					const invalidEmails = JSON.parse(jqXHR.responseText);
					Array.from(tbody.getElementsByTagName("input")).forEach(input => {
						if (invalidEmails.includes(input.value)) {
							const td = input.parentElement.nextElementSibling;
							td.removeAttribute("style");
						}
					});
				} catch (e) {
					// Generic error (e.g., user not found) — show message
					alert(jqXHR.responseText);
				}
			}

		}).always(function() {
			submitButton.disabled = false;
		});
	});
	document.body.prepend(modal);

	function resetInvalidFlags() {
		Array.from(tbody.querySelectorAll("td[data-isinvalid='true']")).forEach(td => {
			td.style.display = "none";
		});
	}

	function getSubmitButton() {
		const submitButton = document.createElement("button");
		submitButton.type = "submit";
		submitButton.style.marginRight = "14px";
		submitButton.textContent = "Update Sharing";
		return submitButton;
	}

	function getCloseButton() {
		const closeButton = document.createElement("button");
		closeButton.textContent = "Close";
		closeButton.classList.add("deleteButton");
		closeButton.type = "button";
		closeButton.addEventListener("click", function() {
			document.getElementById("emailModal").remove();
		});
		return closeButton;
	}

	function getEmailRow() {
		const row = document.createElement("tr");
		let cell = document.createElement("td");
		row.append(cell);
		const deleteButton = document.createElement("button");
		deleteButton.type = "button";
		deleteButton.classList.add("deleteButton");
		deleteButton.innerHTML = "&#9587;"
		deleteButton.addEventListener("click", function() {
			row.remove();
		});
		cell.append(deleteButton);
		cell = document.createElement("td");
		row.append(cell);
		const input = document.createElement("input");
		input.type = "text";
		input.name = "email";
		input.required = true; // don't let the user submit an empty string as an email
		cell.append(input);
		cell = document.createElement("td");
		cell.textContent = "Invalid username";
		cell.dataset.isinvalid = "true";
		cell.style.display = "none";
		row.append(cell);
		input.addEventListener("change", () => { cell.style.display = "none"; })
		return row;
	}

	function getAddButton() {
		const addButton = document.createElement("button");
		addButton.type = "button";
		addButton.textContent = "Add User";
		addButton.addEventListener("click", function() {
			const emailRow = getEmailRow();
			tbody.prepend(emailRow);
		});
		return addButton;
	}
}

function duplicateModel() {
	// handle user input when user hits the duplicate model button.
	newName = prompt("Create a duplicate with name", allInputData.modelName)
	while (! /^[\w\s]+$/.test(newName)){
		newName = prompt("Public a copy with new name, only letters, digits and underscore are allowed in the model name.\nPlease rename your new model", allInputData.modelName)
	}
	if (newName) {
		$.ajax({url:"/uniqObjName/Model/" + currentUser + "/" + newName}).done(function(data) {
			if (data.exists) {
				alert("There is already a model named " + newName)
				duplicateModel()
			} else {
				post_to_url("/duplicateModel/" + allInputData.user + "/" + allInputData.modelName+"/", {"newName":newName})
			}
		})
	}
}

function isFormValid() {
	// Form Validation for Safari browsers
	var inputForm = document.getElementsByTagName('form')[0]
	var inputs = document.getElementsByTagName('input')
	var errors = 0
	for (var i = 0; i < inputs.length; i++) {
		var patt = new RegExp(inputs[i].pattern)
		if (!patt.test(inputs[i].value)) {
			inputs[i].style.backgroundColor = 'red'
			inputs[i].focus()
			errors++
		} else {
			inputs[i].style.backgroundColor = 'gainsboro'
		}
	}
	console.log(errors)
	if (errors) {
		alert("Found [" + errors + "] errors, Please fix inputs in red.")
	} else {
		inputForm.submit()
	}
}

function createModelName(modelType, modelName) {
	// get model name before creation and check to make sure it's not a duplicate.
	var username = sessionStorage.getItem('user');
	console.log(username)
	if (typeof(modelName)==='undefined') modelName = '';
	modelName = prompt("Create a model with name", modelName)
	while (! /^[\w\s]+$/.test(modelName)){
		modelName = prompt("Only letters, digits and underscore are allowed in the model name.\nPlease rename your new model")
	}
	if (modelName) {
		$.ajax({
			url:"/uniqObjName/Model/" + username + "/" + modelName
		}).done(function(data) {
			if (data.exists) {
				alert("There is already a model named " + modelName)
				createModelName(modelType, modelName)
			} else {
				post_to_url("/newModel" + "/"+ modelType + "/" + modelName)
			}
		}).fail(function(jqXHR, textStatus, errorThrown) {
			alert("AJAX request failed to get a successful response from the server.");
		});
	}
}

function editFeeder(modelName, feederNum) {
	// TODO: remove, replace with just having the button open a new window with the edit feeder route. But... can buttons be forced to open a new window?
	console.log("modelName:",modelName)
	studyUser = allInputData.user
	window.open('/displayMap/' + studyUser + '/' + modelName + '/' + feederNum, '_blank');
}