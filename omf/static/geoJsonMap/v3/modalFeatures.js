export { getLoadingSpan, getAnonymizationButton, getSaveButton, getRawDataButton, getRenameButton, getLoadFeederButton, getBlankFeederButton, getWindmilButton, getGridlabdButton, getCymdistButton, getOpendssButton, getAmiButton, getAttachmentsButton, getClimateButton, getScadaButton, getColorButton, getGeojsonButton, getSearchButton, getAddComponentsButton};
import { ColorModal } from './colorModal.js';
import { Feature } from  './feature.js';
import { FeatureController } from './featureController.js';
import { GeojsonModal } from './geojsonModal.js';
import { hideModalInsert } from './main.js'
import { Nav } from './nav.js';
import { TopTab } from './topTab.js';
import { IconLabelButton } from '../v4/ui-components/iconlabel-button/iconlabel-button.js';
import { PropTable } from '../v4/ui-components/prop-table/prop-table.js';
import { LoadingSpan } from '../v4/ui-components/loading-span/loading-span.js';
import { DropdownDiv } from '../v4/ui-components/dropdown-div/dropdown-div.js';

/*
 * @returns {Modal}
 */
function getLoadingSpan() {
    const loadingSpan = new LoadingSpan();
    loadingSpan.update({text: 'Loading map...'});
    return loadingSpan;
}

/**
 * @param {Feature} - an ObservableInterface instance
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getAnonymizationTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const propTable = new PropTable();
    propTable.insertTHeadRow({elements: ['Anonymization'], colspans: [2]});
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTBodyRow({elements: ['Names and Labels'], colspans: [2]});
    // - namesAndLabelsSelect
    const namesAndLabelsSelect = document.createElement('select');
    namesAndLabelsSelect.name = 'anonymizeNameOption';
    let option = document.createElement('option');
    option.text = 'No Change';
    option.value = 'noChange';
    namesAndLabelsSelect.add(option);
    option = document.createElement('option');
    option.text = 'Pseudonymize';
    option.value = 'pseudonymize';
    namesAndLabelsSelect.add(option);
    option = document.createElement('option');
    option.text = 'Randomize';
    option.value = 'randomize';
    namesAndLabelsSelect.add(option);
    namesAndLabelsSelect.addEventListener('change', function() {
        observable.setProperty(this.name, this.value, 'formProps');
    });
    propTable.insertTBodyRow({elements: [namesAndLabelsSelect], colspans: [2]});
    propTable.insertTBodyRow({elements: ['Locations'], colspans: [2]});
    // - locationsSelect
    const locationsSelect = document.createElement('select');
    locationsSelect.name = 'anonymizeLocationOption';
    option = document.createElement('option');
    option.text = 'No change';
    option.value = 'noChange';
    locationsSelect.add(option);
    option = document.createElement('option');
    option.text = 'Randomize';
    option.value = 'randomize';
    locationsSelect.add(option);
    option = document.createElement('option');
    option.text = 'Force layout';
    option.value = 'forceLayout';
    locationsSelect.add(option);
    option = document.createElement('option');
    option.text = 'Translate';
    option.value = 'translation';
    locationsSelect.add(option);
    propTable.insertTBodyRow({elements: [locationsSelect], colspans: [2]});
    // - Scale input
    const scaleInput = document.createElement('input');
    scaleInput.name = 'scale';
    scaleInput.value = '.01';
    scaleInput.pattern = '(\\d+)?(\\.\\d+)?';
    scaleInput.addEventListener('change', function() {
        const value = this.value.trim();
        observable.setProperty(this.name, value, 'formProps');
    });
    // - Scale dropdown
    const forceLayoutDropdown = new DropdownDiv();
    const forceLayoutTable = new PropTable();
    let div = document.createElement('div');
    let span = document.createElement('span');
    span.textContent = 'Force layout with following scale factor: '
    div.append(span);
    div.append(scaleInput);
    forceLayoutTable.insertTBodyRow({elements: [div]});
    forceLayoutTable.insertTBodyRow({elements: ['Estimates: 0.001 = street-density, 0.01 = neighborhood-density, 0.1 = city-density, 1 = state-density'], colspans: [2]});
    forceLayoutDropdown.insertElement({element: forceLayoutTable.div});
    propTable.insertTBodyRow({elements: [forceLayoutDropdown.div], colspans: [2]});
    // - Location inputs and dropdown
    const translateDropdown = new DropdownDiv();
    const translateTable = new PropTable();
    const coordinatesInput = document.createElement('input');
    //  - Coordinates input
    coordinatesInput.name = 'new_center_coords';
    coordinatesInput.placeholder = 'lat°, lon°';
    coordinatesInput.pattern = '\\(?(-?\\d+(\\.\\d+)?),\\s*(-?\\d+(\\.\\d+)?)\\)?';
    coordinatesInput.addEventListener('change', function() {
        const value = this.value.trim();
        observable.setProperty(this.name, value, 'formProps');
    });
    translateTable.insertTBodyRow({elements: ['Shift center to', coordinatesInput, 'coordinates within the contiguous/non-contiguous USA']});
    //  - Horizontal translation input
    const horizontalTranslationInput = document.createElement('input');
    horizontalTranslationInput.name = 'translateRight';
    horizontalTranslationInput.placeholder = '(+/-)meters';
    horizontalTranslationInput.pattern = '[\\-+]?\\d+';
    horizontalTranslationInput.addEventListener('change', function() {
        const value = this.value.trim();
        observable.setProperty(this.name, value, 'formProps');
    });
    translateTable.insertTBodyRow({elements: ['Translate', horizontalTranslationInput, 'meters rightwards']});
    //  - Vertical translation input
    const verticalTranslationInput = document.createElement('input');
    verticalTranslationInput.name = 'translateUp'
    verticalTranslationInput.placeholder = '(+/-)meters';
    verticalTranslationInput.pattern = '[\\-+]?\\d+';
    verticalTranslationInput.addEventListener('change', function() {
        const value = this.value.trim();
        observable.setProperty(this.name, value, 'formProps');
    });
    translateTable.insertTBodyRow({elements: ['Translate', verticalTranslationInput, 'meters upwards']});
    //  - Rotation input
    const rotationInput = document.createElement('input');
    rotationInput.name = 'rotate';
    rotationInput.placeholder = '(+/-)angle°';
    rotationInput.pattern = '[\\-+]?\\d+(\\.\\d+)?'
    rotationInput.addEventListener('change', function() {
        const value = this.value.trim();
        observable.setProperty(this.name, value, 'formProps');
    });
    translateTable.insertTBodyRow({elements: ['Rotate', rotationInput, 'degrees counterclockwise']});
    translateDropdown.insertElement({element: translateTable.div});
    propTable.insertTBodyRow({elements: [translateDropdown.div], colspans: [2]});
    locationsSelect.addEventListener('change', function() {
        observable.setProperty(this.name, this.value, 'formProps');
        if (this.value === 'translation') {
            translateDropdown.div.getElementsByClassName('contentdiv')[0].classList.add('-expanded');
        } else {
            translateDropdown.div.getElementsByClassName('contentdiv')[0].classList.remove('-expanded');
        }
        if (this.value === 'forceLayout') {
            forceLayoutDropdown.div.getElementsByClassName('contentdiv')[0].classList.add('-expanded');
        } else {
            forceLayoutDropdown.div.getElementsByClassName('contentdiv')[0].classList.remove('-expanded');
        }
    });
    // - Electrical properties
    propTable.insertTBodyRow({elements: ['Electrical properties'], colspans: [2]});
    // - conductorCheckbox
    const conductorCheckbox = document.createElement('input');
    conductorCheckbox.id = 'modifyLengthSize';
    conductorCheckbox.type = 'checkbox';
    conductorCheckbox.name = 'modifyLengthSize';
    conductorCheckbox.addEventListener('change', function() {
        let value = '';
        if (this.checked) {
            value = 'modifyLengthSize';
        }
        observable.setProperty(this.name, value, 'formProps');
    });
    const conductorLabel = document.createElement('label');
    conductorLabel.htmlFor = 'modifyLengthSize';
    conductorLabel.innerText = 'Modify conductor length and cable size';
    div = document.createElement('div');
    div.append(conductorCheckbox, conductorLabel);
    propTable.insertTBodyRow({elements: [div]});
    // - smoothAMICheckbox
    const smoothAMICheckbox = document.createElement('input');
    smoothAMICheckbox.id = 'smoothLoadGen';
    smoothAMICheckbox.type = 'checkbox';
    smoothAMICheckbox.name = 'smoothLoadGen';
    smoothAMICheckbox.addEventListener('change', function() {
        let value = '';
        if (this.checked) {
            value = 'smoothLoadGen';
        }
        observable.setProperty(this.name, value, 'formProps');
    });
    const smoothAMILabel = document.createElement('label');
    smoothAMILabel.htmlFor = 'smoothLoadGen';
    smoothAMILabel.innerText = 'Smooth AMI Loadshapes';
    div = document.createElement('div');
    div.append(smoothAMICheckbox, smoothAMILabel);
    propTable.insertTBodyRow({elements: [div]});
    // - shuffleLoadsCheckbox
    const shuffleDropdown = new DropdownDiv();
    const shuffleLoadsCheckbox = document.createElement('input');
    shuffleLoadsCheckbox.id = 'shuffleLoadGen';
    shuffleLoadsCheckbox.type = 'checkbox';
    shuffleLoadsCheckbox.name = 'shuffleLoadGen';
    shuffleLoadsCheckbox.addEventListener('change', function() {
        let value = '';
        if (this.checked) {
            value = 'shuffleLoadGen';
            shuffleDropdown.div.getElementsByClassName('contentdiv')[0].classList.add('-expanded');
        } else {
            shuffleLoadsInput.setCustomValidity('');
            shuffleLoadsInput.value = '';
            shuffleDropdown.div.getElementsByClassName('contentdiv')[0].classList.remove('-expanded');
        }
        observable.setProperty(this.name, value, 'formProps');
    });
    const shuffleLoadsLabel = document.createElement('label');
    shuffleLoadsLabel.htmlFor = 'shuffleLoadGen';
    shuffleLoadsLabel.innerText = 'Shuffle loads and generators';
    const shuffleLoadsInput = document.createElement('input');
    shuffleLoadsInput.name = 'shufflePerc';
    shuffleLoadsInput.placeholder = '(1-100)'
    shuffleLoadsInput.pattern = '(\\d+)?(\\.\\d+)?';
    shuffleLoadsInput.addEventListener('change', function() {
        this.setCustomValidity('');
        const value = +this.value.trim();
        if (isNaN(value)) {
            this.setCustomValidity('Please enter a valid integer or float.');
            this.reportValidity();
        } else if (value <= 0 || value > 100 || this.validity.patternMismatch) {
            this.setCustomValidity('Please enter a valid integer or float greater than 0 and less than or equal to 100.');
            this.reportValidity();
        } else if (this.validity.valid) {
            observable.setProperty(this.name, value, 'formProps');
        }
    });
    div = document.createElement('div');
    div.append(shuffleLoadsCheckbox, shuffleLoadsLabel);
    propTable.insertTBodyRow({elements: [div]});
    const shuffleTable = new PropTable();
    shuffleTable.insertTBodyRow({elements: ['Shuffle', shuffleLoadsInput, 'percent']});
    shuffleDropdown.insertElement({element: shuffleTable.div});
    propTable.insertTBodyRow({elements: [shuffleDropdown.div], colspans: [2]});
    // - addNoiseCheckbox
    const addNoiseDropdown = new DropdownDiv();
    const addNoiseCheckbox = document.createElement('input');
    addNoiseCheckbox.id = 'addNoise';
    addNoiseCheckbox.type = 'checkbox';
    addNoiseCheckbox.name = 'addNoise';
    addNoiseCheckbox.addEventListener('change', function() {
        let value = '';
        if (this.checked) {
            value = 'addNoise';
            addNoiseDropdown.div.getElementsByClassName('contentdiv')[0].classList.add('-expanded');
        } else {
            addNoiseInput.setCustomValidity('');
            addNoiseInput.value = '';
            addNoiseDropdown.div.getElementsByClassName('contentdiv')[0].classList.remove('-expanded');
        }
        observable.setProperty(this.name, value, 'formProps');
    });
    const addNoiseLabel = document.createElement('label');
    addNoiseLabel.htmlFor = 'addNoise';
    addNoiseLabel.innerText = 'Add Noise';
    const addNoiseInput = document.createElement('input');
    addNoiseInput.name = 'noisePerc';
    addNoiseInput.placeholder = '(1-100)'
    addNoiseInput.pattern = '(\\d+)?(\\.\\d+)?';
    addNoiseInput.addEventListener('change', function() {
        this.setCustomValidity('');
        const value = +this.value.trim();
        if (isNaN(value)) {
            this.setCustomValidity('Please enter a valid integer or float.');
            this.reportValidity();
        } else if (value <= 0 || value > 100 || this.validity.patternMismatch) {
            this.setCustomValidity('Please enter a valid integer or float greater than 0 and less than or equal to 100.');
            this.reportValidity();
        } else if (this.validity.valid) {
            observable.setProperty(this.name, value, 'formProps');
        }
    });
    div = document.createElement('div');
    div.append(addNoiseCheckbox, addNoiseLabel);
    propTable.insertTBodyRow({elements: [div]});
    const addNoiseTable = new PropTable();
    addNoiseTable.insertTBodyRow({elements: ['Add', addNoiseInput, 'percent noise']});
    addNoiseDropdown.insertElement({element: addNoiseTable.div});
    propTable.insertTBodyRow({elements: [addNoiseDropdown.div], colspans: [2]});
    // - Submit button
    const button = new IconLabelButton({text: 'Submit'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    // - LoadingSpan
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], position: 'prepend'})
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', async function() {
        if (coordinatesInput.checkValidity() && horizontalTranslationInput.checkValidity() && verticalTranslationInput.checkValidity() && rotationInput.checkValidity() && scaleInput.checkValidity() && shuffleLoadsInput.checkValidity() && addNoiseInput.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            const saveFeature = _getSaveFeature();
            saveFeature.setProperty('feederObjectJson', JSON.stringify(controller.observableGraph.getObservableExportData()), 'formProps');
            const saveLoadingSpan = _getSaveLoadingSpan(controller);
            modalInsert.replaceChildren(saveLoadingSpan.span);
            await controller.submitFeature(saveFeature, saveLoadingSpan, null, false);
            modalInsert.removeEventListener('click', hideModalInsert);
            document.getElementById('modalInsert').classList.add('visible');
            modalInsert.replaceChildren(propTable.div);
            loadingSpan.update({text: 'Anonymization working...'});
            await controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            coordinatesInput.reportValidity();
            horizontalTranslationInput.reportValidity();
            verticalTranslationInput.reportValidity();
            rotationInput.reportValidity();
            scaleInput.reportValidity();
            shuffleLoadsInput.reportValidity();
            addNoiseInput.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a FeatureController instance
 * @returns {HTMLButtonElement}
 */
function getAnonymizationButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:anonymization',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${gThisFeederName}`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/anonymize/${gThisOwner}/${gThisFeederName}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                anonymizeNameOption: 'noChange',
                anonymizeLocationOption: 'noChange',
                new_center_coords: '',
                translateRight: '',
                translateUp: '',
                rotate: '',
                // - In Python, bool('') returns a False bool. FormData objects can only send strings
                modifyLengthSize: '',       // 'modifyLengthSize',
                smoothLoadGen: '',          // 'smoothLoadGen',
                shuffleLoadGen: '',         // 'shuffleLoadGen',
                shufflePerc: '',
                addNoise: '',               // 'addNoise'
                noisePerc: '',
                scale: '.01' 
            },
        },
        type: 'Feature'
    });
    const propTable = _getAnonymizationTable(feature, controller);
    const modalInsert = document.getElementById('modalInsert');
    const button = new IconLabelButton({text: 'Anonymization...'});
    button.button.classList.add('-white');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {Modal}
 */
function _getSaveLoadingSpan(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const loadingSpan = new LoadingSpan();
    loadingSpan.update({text: 'Saving...'});
    return loadingSpan;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getSaveButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const saveFeature = _getSaveFeature();
    const loadingSpan = _getSaveLoadingSpan(controller);
    const button = new IconLabelButton({text: 'Save'});
    button.button.classList.add('-white');
    button.button.id = 'saveDiv';
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.removeEventListener('click', hideModalInsert);
        modalInsert.replaceChildren(loadingSpan.span);
        modalInsert.classList.add('visible');
        // - I only export features that were originally in the OMD (i.e. those features with numeric tree keys)
        saveFeature.setProperty('feederObjectJson', JSON.stringify(controller.observableGraph.getObservableExportData()), 'formProps')
        controller.submitFeature(saveFeature, loadingSpan, null, false);
    });
    return button.button;
}

/**
 * @returns {Feature}
 */
function _getSaveFeature() {
    return new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:save',
            urlProps: {
                submitUrl: {
                    method: 'POST',
                    url: `/saveFeeder/${gThisOwner}/${gThisModelName}/${gThisFeederName}/${gThisFeederNum}`
                }
            },
            // - I need to read all of the data every time the save button is clicked, so set "feederObjectJson" in the event handler function
            formProps: {},
        },
        type: 'Feature'
    });
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @param {ColorModal} colorModal - a ColorModal instance
 * @returns {PropTable}
 */
function _getRawDataTable(controller, colorModal) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    if (!(colorModal instanceof ColorModal)) {
        throw TypeError('The "colorModal" argument must be instanceof ColorModal.');
    }
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['Download GeoJSON file'], colspans: [2]});
    const label = document.createElement('label');
    label.htmlFor = 'addColoringProperties';
    label.innerText = 'Add coloring CSVs properties to GeoJSON file';
    const colorCheckbox = document.createElement('input');
    colorCheckbox.type = 'checkbox';
    colorCheckbox.id = 'addColoringProperties'
    propTable.insertTBodyRow({elements: [label, colorCheckbox]});
    const button = new IconLabelButton({text: 'Download'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    button.button.addEventListener('click', function() {
        const exportData = controller.observableGraph.getObservableExportData();
        if (colorCheckbox.checked) {
            for (const [filename, colorFile] of Object.entries(colorModal.getColorFiles())) {
                for (const [columnIndex, colorMap] of Object.entries(colorFile.getColorMaps())) {
                    const propertyName = colorMap.getColumnName();
                    for (const feature of exportData.features) {
                        if (feature.properties.hasOwnProperty('treeProps') && feature.properties.treeProps.hasOwnProperty('name')) {
                            const name = feature.properties.treeProps.name;
                            // - We don't handle the case where multiple features share the same name. In such a situation, both exported features
                            //   will have the same coloring data inserted into them
                            if (colorMap.getNameToValue().hasOwnProperty(name)) {
                                // - If the feature already has the propertyName, that means that either one CSV has multiple columns with the same
                                //   heading, or multiple CSVs have the same column heading. To deal with that, prefix the propertyName
                                if (feature.properties.hasOwnProperty(propertyName)) {
                                    feature.properties[`${filename}_${propertyName}`] = colorMap.getNameToValue()[name].value;
                                } else {
                                    feature.properties[propertyName] = colorMap.getNameToValue()[name].value;
                                }
                            }
                        }
                    }
                }
            }
        }
        const a = document.createElement('a');
        const blob = new Blob([JSON.stringify(exportData)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        a.setAttribute('href', url);
        a.setAttribute('download', 'geojson.json');
        a.click();
        URL.revokeObjectURL(url);
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @param {ColorModal} colorModal - a ColorModal instance
 * @returns {HTMLButtonElement}
 */
function getRawDataButton(controller, colorModal) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    if (!(colorModal instanceof ColorModal)) {
        throw TypeError('The "colorModal" argument must be instanceof ColorModal.');
    }
    const propTable = _getRawDataTable(controller, colorModal);
    const modalInsert = document.getElementById('modalInsert');
    const button = new IconLabelButton({text: 'Download data...'});
    button.button.classList.add('-white');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getRenameTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - Input
    const input = _getNameInput(observable, function(newName) {
        const fileExistsUrl = {
            method: 'GET',
            url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${newName}`
        }
        observable.setProperty('fileExistsUrl', fileExistsUrl, 'urlProps');
        const submitUrl = {
            method: 'POST',
            url: `/renameFeeder/${gThisOwner}/${gThisModelName}/${gThisFeederName}/${newName}/${gThisFeederNum}`
        }
        observable.setProperty('submitUrl', submitUrl, 'urlProps');
    });
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['Rename feeder'], colspans: [2]});
    propTable.insertTBodyRow({elements: ['New feeder name:', input]});
    const button = new IconLabelButton({text: 'Rename'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', async function() {
        if (input.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            const saveFeature = _getSaveFeature();
            saveFeature.setProperty('feederObjectJson', JSON.stringify(controller.observableGraph.getObservableExportData()), 'formProps')
            const saveLoadingSpan = _getSaveLoadingSpan(controller);
            modalInsert.replaceChildren(saveLoadingSpan.span);
            await controller.submitFeature(saveFeature, saveLoadingSpan, null, false);
            document.getElementById('modalInsert').classList.add('visible');
            loadingSpan.update({text: 'Renaming feeder...'});
            modalInsert.replaceChildren(propTable.div);
            modalInsert.removeEventListener('click', hideModalInsert);
            await controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            input.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getRenameButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:rename',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/Default Name`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/renameFeeder/${gThisOwner}/${gThisModelName}/${gThisFeederName}/Default Name/${gThisFeederNum}`
                }
            }
        },
        type: 'Feature'
    });
    const propTable = _getRenameTable(feature, controller);
    const modalInsert = document.getElementById('modalInsert');
    const button = new IconLabelButton({text: 'Rename...'});
    button.button.classList.add('-white');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getLoadFeederTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - Create a list of public feeders
    let publicFeeders = [];
    if (gPublicFeeders !== null) {
        publicFeeders = [...gPublicFeeders];
        publicFeeders.sort((a, b) => a.name.localeCompare(b.name, 'en', {numeric: true}));
    }
    const publicFeedersTable = new PropTable();
    publicFeedersTable.insertTHeadRow({elements: ['Public feeders']});
    const publicFeedersLoadingSpan = new LoadingSpan();
    publicFeedersLoadingSpan.span.classList.add('-yellow', '-hidden');
    publicFeedersTable.insertTHeadRow({elements: [publicFeedersLoadingSpan.span], position: 'prepend'});
    const modalInsert = document.getElementById('modalInsert');
    publicFeeders.map(obj => {
        const buttonTextDiv = document.createElement('div');
        const nameDiv = document.createElement('div');
        nameDiv.textContent = obj.name;
        buttonTextDiv.append(nameDiv);
        const modelDiv = document.createElement('div');
        modelDiv.textContent = `from "${obj.model}"`;
        buttonTextDiv.append(modelDiv);
        const button = new IconLabelButton({text: buttonTextDiv});
        button.button.classList.add('-white');
        button.button.addEventListener('click', async function() {
            modalInsert.removeEventListener('click', hideModalInsert);
            observable.setProperty('fileExistsUrl', {
                method: 'GET', 
                url: `/uniqObjName/Feeder/public/${obj.model}/${obj.name}`
            }, 'urlProps');
            observable.setProperty('submitUrl', {
                method: 'POST',
                url: `/loadFeeder/${obj.name}/${obj.model}/${gThisModelName}/${gThisFeederNum}/public/${gThisOwner}`,
            }, 'urlProps');
            await controller.submitFeature(observable, publicFeedersLoadingSpan);
        });
        return button.button;
    }).forEach(button => publicFeedersTable.insertTBodyRow({elements: [button]}));
    // - Create list of user feeders
    let userFeeders = [];
    if (gUserFeeders !== null) {
        userFeeders = [...gUserFeeders];
        userFeeders.sort((a, b) => a.name.localeCompare(b.name, 'en', {numeric: true}));
    }
    const userFeedersTable = new PropTable();
    userFeedersTable.insertTHeadRow({elements: ['User feeders']});
    const userFeedersLoadingSpan = new LoadingSpan();
    userFeedersLoadingSpan.span.classList.add('-yellow', '-hidden');
    userFeedersTable.insertTHeadRow({elements: [userFeedersLoadingSpan.span], position: 'prepend'});
    userFeeders.map(obj => {
        const buttonTextDiv = document.createElement('div');
        const nameDiv = document.createElement('div');
        nameDiv.textContent = obj.name;
        buttonTextDiv.appendChild(nameDiv);
        const modelDiv = document.createElement('div');
        modelDiv.textContent = `from "${obj.model}"`;
        buttonTextDiv.append(modelDiv);
        const button = new IconLabelButton({text: buttonTextDiv});
        button.button.classList.add('-white');
        button.button.addEventListener('click', async function() {
            modalInsert.removeEventListener('click', hideModalInsert);
            observable.setProperty('fileExistsUrl', {
                method: 'GET',
                // - Let's say I'm an admin viewing some user's file. gCurrentUser = "admin" and gThisOwner = "test". userFeeders is all of the
                //   admin's feeders. Therefore, to see if the admin's feeders exist in order to load them, I need /uniqObjName to check the current
                //   user's feeders, NOT the owner's feeders. Usually, gThisOwner === gCurrentUser, but this one special case is why this url is
                //   different
                url: `/uniqObjName/Feeder/${gCurrentUser}/${obj.model}/${obj.name}`
            }, 'urlProps');
            observable.setProperty('submitUrl', {
                method: 'POST',
                url: `/loadFeeder/${obj.name}/${obj.model}/${gThisModelName}/${gThisFeederNum}/${gCurrentUser}/${gThisOwner}`,
            }, 'urlProps');
            await controller.submitFeature(observable, userFeedersLoadingSpan); 
        });
        return button.button;
    }).forEach(button => userFeedersTable.insertTBodyRow({elements: [button]}));
    const propTable = new PropTable();
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.div.id = 'loadFeederTable';
    propTable.insertTHeadRow({elements: ['Load feeder'], colspans: [2]});
    propTable.insertTBodyRow({elements: [publicFeedersTable.div, userFeedersTable.div]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getLoadFeederButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:loadFeeder',
            urlProps: {},
            formProps: {
                referrer: 'distribution'
            }
        },
        'type': 'Feature'
    });
    const propTable = _getLoadFeederTable(feature, controller);
    const button = new IconLabelButton({text: 'Load from model...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getBlankFeederTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - Input
    const input = _getNameInput(observable, function(newName) {
        observable.setProperty('feederNameNew', newName, 'formProps');
    });
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['New blank feeder:'], colspans: [2]});
    propTable.insertTBodyRow({elements: ['Blank feeder name', input]});
    const button = new IconLabelButton({text: 'Submit'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', async function() {
        if (input.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            loadingSpan.update({text: 'Creating new blank feeder...'});
            await controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            input.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getBlankFeederButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:blankFeeder',
            urlProps: {
                submitUrl: {
                    method: 'POST',
                    url: `/newBlankFeeder/${gThisOwner}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                feederNameNew: 'Default Name',
                feederNum: gThisFeederNum,
                referrer: 'distribution'
            }
        },
        type: 'Feature'
    });
    const propTable = _getBlankFeederTable(feature, controller);
    const button = new IconLabelButton({text: 'New blank feeder...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getWindmilTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - Name input
    const nameInput = _getNameInput(observable, function(newName) {
        observable.setProperty('feederNameM', newName, 'formProps');
        const fileExistsUrl = {
            method: 'GET',
            url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${newName}`
        }
        observable.setProperty('fileExistsUrl', fileExistsUrl, 'urlProps');
    });
    nameInput.id = 'milsoftNameInput';
    const nameLabel = document.createElement('label');
    nameLabel.htmlFor = 'milsoftNameInput';
    nameLabel.innerText = 'Name';
    // - .std file input
    const stdInput = document.createElement('input');
    stdInput.type = 'file';
    stdInput.accept = '.std';
    stdInput.required = true;
    stdInput.id = 'milsoftStdInput';
    stdInput.addEventListener('change', function() {
        const stdFile = this.files[0];
        observable.setProperty('stdFile', stdFile, 'formProps');
    });
    const stdLabel = document.createElement('label');
    stdLabel.htmlFor = 'milsoftStdInput';
    stdLabel.innerHTML = 'Data File (.std)';
    // .seq file input
    const seqInput = document.createElement('input');
    seqInput.type = 'file';
    seqInput.accept = '.seq';
    seqInput.required = true;
    seqInput.id = 'milsoftSeqInput';
    seqInput.addEventListener('change', function() {
        const seqFile = this.files[0];
        observable.setProperty('seqFile', seqFile, 'formProps');
    });
    const seqLabel = document.createElement('label');
    seqLabel.htmlFor = 'milsoftSeqInput';
    seqLabel.innerText = 'Equipment File (.seq)';
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['Milsoft conversion'], colspans: [2]});
    propTable.insertTBodyRow({elements: [nameLabel, nameInput]});
    propTable.insertTBodyRow({elements: [stdLabel, stdInput]});
    propTable.insertTBodyRow({elements: [seqLabel, seqInput]});
    const button = new IconLabelButton({text: 'Import'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    button.button.addEventListener('click', function() {
        if (nameInput.checkValidity() && stdInput.checkValidity() && seqInput.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            loadingSpan.update({text: 'Importing file...', show: true});
            controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            nameInput.reportValidity();
            stdInput.reportValidity();
            seqInput.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getWindmilButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:windmil',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/Default Name`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/milsoftImport/${gThisOwner}`                    
                }
            },
            formProps: {
                modelName: gThisModelName,
                feederNameM: 'Default Name',
                feederNum: gThisFeederNum,
                stdFile: '',
                seqFile: ''
            }
        },
        type: 'Feature'
    });
    const propTable = _getWindmilTable(feature, controller);
    const button = new IconLabelButton({text: 'Windmil conversion...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getGridlabdTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - Name input
    const nameInput = _getNameInput(observable, function(newName) {
        observable.setProperty('feederNameG', newName, 'formProps');
        const fileExistsUrl = {
            method: 'GET',
            url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${newName}`
        }
        observable.setProperty('fileExistsUrl', fileExistsUrl, 'urlProps');
    });
    nameInput.id = 'gridlabdNameInput';
    const nameLabel = document.createElement('label');
    nameLabel.htmlFor = 'gridlabdNameInput';
    nameLabel.innerText = 'Name';
    // - .glm file input
    const glmInput = document.createElement('input');
    glmInput.type = 'file';
    glmInput.accept = '.glm';
    glmInput.required = true;
    glmInput.id = 'glmInput';
    glmInput.addEventListener('change', function() {
        const glmFile = this.files[0];
        observable.setProperty('glmFile', glmFile, 'formProps');
    });
    const glmLabel = document.createElement('label');
    glmLabel.htmlFor = 'glmInput';
    glmLabel.innerHTML = 'Data File (.glm)';
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['GridLABD-D Conversion'], colspans: [2]});
    propTable.insertTBodyRow({elements: [nameLabel, nameInput]});
    propTable.insertTBodyRow({elements: [glmLabel, glmInput]});
    const button = new IconLabelButton({text: 'Import'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        if (nameInput.checkValidity() && glmInput.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            loadingSpan.update({text: 'Importing file...', show: true});
            controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            nameInput.reportValidity();
            glmInput.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getGridlabdButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('"controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:gridlabd',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/Default Name`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/gridlabdImport/${gThisOwner}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                feederNameG: 'Default Name',
                feederNum: gThisFeederNum,
                glmFile: ''
            }
        },
        type: 'Feature'
    });
    const propTable = _getGridlabdTable(feature, controller);

    const button = new IconLabelButton({text: 'GridLAB-D conversion...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}
/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getCymdistTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - Name input
    const nameInput = _getNameInput(observable, function(newName) {
        observable.setProperty('feederNameC', newName, 'formProps');
        const fileExistsUrl = {
            method: 'GET',
            url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${newName}`
        }
        observable.setProperty('fileExistsUrl', fileExistsUrl, 'urlProps');
    });
    nameInput.id = 'cymdistNameInput';
    const nameLabel = document.createElement('label');
    nameLabel.htmlFor = 'cymdistNameInput';
    nameLabel.innerText = 'Name';
    // - .mdb file input
    const mdbInput = document.createElement('input');
    mdbInput.type = 'file';
    mdbInput.accept = '.mdb';
    mdbInput.required = true;
    mdbInput.id = 'mdbInput';
    mdbInput.addEventListener('change', function() {
        const mdbFile = this.files[0];
        observable.setProperty('mdbNetFile', mdbFile, 'formProps');
    });
    const mdbLabel = document.createElement('label');
    mdbLabel.htmlFor = 'mdbInput';
    mdbLabel.innerHTML = 'Network File (.mdb)';
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['Cyme conversion'], colspans: [2]});
    propTable.insertTBodyRow({elements: [nameLabel, nameInput]});
    propTable.insertTBodyRow({elements: [mdbLabel, mdbInput]});
    const button = new IconLabelButton({text: 'Import'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    button.button.addEventListener('click', function() {
        if (nameInput.checkValidity() && mdbInput.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            loadingSpan.update({text: 'Importing file...', show: true});
            controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            nameInput.reportValidity();
            mdbInput.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getCymdistButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:cymdist',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/Default Name`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/cymeImport/${gThisOwner}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                feederNum: gThisFeederNum,
                feederNameC: 'Default Name',
                mdbNetFile: ''
            }
        },
        type: 'Feature'
    });
    const propTable = _getCymdistTable(feature, controller);

    const button = new IconLabelButton({text: 'CYMDIST conversion...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getOpendssTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - Name input
    const nameInput = _getNameInput(observable, function(newName) {
        observable.setProperty('feederNameOpendss', newName, 'formProps');
        const fileExistsUrl = {
            method: 'GET',
            url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${newName}`
        }
        observable.setProperty('fileExistsUrl', fileExistsUrl, 'urlProps');
    });
    nameInput.id = 'opendssNameInput';
    const nameLabel = document.createElement('label');
    nameLabel.htmlFor = 'opendssNameInput';
    nameLabel.innerText = 'Name';
    // - .dss file input
    const dssInput = document.createElement('input');
    dssInput.type = 'file';
    dssInput.accept = '.dss';
    dssInput.required = true;
    dssInput.id = 'dssInput';
    dssInput.addEventListener('change', function() {
        const dssFile = this.files[0];
        observable.setProperty('dssFile', dssFile, 'formProps');
    });
    const dssLabel = document.createElement('label');
    dssLabel.htmlFor = 'dssInput';
    dssLabel.innerHTML = 'Data File (.dss)';
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['OpenDSS Conversion'], colspans: [2]});
    propTable.insertTBodyRow({elements: [nameLabel, nameInput]});
    propTable.insertTBodyRow({elements: [dssLabel, dssInput]});
    const button = new IconLabelButton({text: 'Import'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    button.button.addEventListener('click', function() {
        if (nameInput.checkValidity() && dssInput.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            loadingSpan.update({text: 'Importing file...', show: true});
            controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            nameInput.reportValidity();
            dssInput.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getOpendssButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:opendss',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/Default Name`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/opendssImport/${gThisOwner}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                feederNameOpendss: 'Default Name',
                feederNum: gThisFeederNum,
                dssFile: ''
            }
        },
        type: 'Feature'
    });
    const propTable = _getOpendssTable(feature, controller);

    const button = new IconLabelButton({text: 'OpenDSS conversion...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getAmiTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - csv file input
    const amiInput = document.createElement('input');
    amiInput.type = 'file';
    amiInput.accept = '.csv';
    amiInput.required = true;
    amiInput.id = 'amiInput'; 
    amiInput.addEventListener('change', function() {
        const amiFile = this.files[0];
        observable.setProperty('amiFile', amiFile, 'formProps');
    });
    const amiLabel = document.createElement('label');
    amiLabel.htmlFor = 'amiInput';
    amiLabel.innerHTML = 'File containing AMI load data (.csv)';
    // - Format help anchor
    const anchor = document.createElement('a');
    anchor.href = 'https://github.com/dpinney/omf/wiki/Tools-~-gridEdit#ami-load-modeling';
    anchor.textContent = 'Format Help';
    anchor.target = '_blank';
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['AMI Profiles'], colspans: [2]});
    propTable.insertTBodyRow({elements: [anchor], colspans: [2]});
    propTable.insertTBodyRow({elements: [amiLabel, amiInput]});
    propTable.insertTBodyRow({elements: ['Note: model "Simulation Start Data" should lie within the AMI profile\'s dates'], colspans: [2]});
    const button = new IconLabelButton({text: 'Import'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    button.button.addEventListener('click', function() {
        if (amiInput.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            loadingSpan.update({text: 'Importing file...', show: true});
            controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            amiInput.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLDivElement}
 */
function getAmiButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('"controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:ami',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${gThisFeederName}`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/loadModelingAmi/${gThisOwner}/${gThisFeederName}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                amiFile: ''
            }
        },
        type: 'Feature'
    });
    const propTable = _getAmiTable(feature, controller);
    const button = new IconLabelButton({text: 'Add AMI profiles...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getAttachmentsTable(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const attachmentsPropTable = new PropTable();
    attachmentsPropTable.div.id = 'attachmentsTable';
    // - Don't close the modal when it is clicked on
    attachmentsPropTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    attachmentsPropTable.insertTHeadRow({elements: ['Attachments'], colspans: [2]});
    const omdFeature = controller.observableGraph.getObservable('omd');
    const attachments = omdFeature.getProperty('attachments', 'meta');
    const textAreaModals = [];
    for (const [key, val] of Object.entries(attachments)) {
        if (typeof val === 'string') {
            const propTable = _getTextAreaTable(key, key, val, attachments, omdFeature);
            textAreaModals.push({
                object: attachments,
                propertyKey: key,
                textArea: propTable.div.querySelector('textarea'),
                feature: omdFeature,
                text: val
            });
            attachmentsPropTable.insertTBodyRow({elements: [propTable.div]});
        } else if (typeof val === 'object') {
            const nestedObjects = _getNestedObjects(val);
            nestedObjects.forEach(obj => {
                for (const [innerKey, text] of Object.entries(obj.object)) {
                    if (typeof text === 'string') {
                        const propTable = _getTextAreaTable(`${obj.namespace} ${innerKey}`, innerKey, text, obj.object, omdFeature);
                        textAreaModals.push({
                            object: obj.object,
                            propertyKey: innerKey,
                            textArea: propTable.div.querySelector('textarea'),
                            feature: omdFeature,
                            text: text
                        });
                        attachmentsPropTable.insertTBodyRow({elements: [propTable.div]});
                    }
                }
            });
        }
    }
    const saveButton = new IconLabelButton({text: 'Save'});
    saveButton.button.classList.add('-blue');
    saveButton.button.getElementsByClassName('label')[0].classList.add('-white');
    saveButton.button.addEventListener('click', function() {
        textAreaModals.forEach(obj => {
            obj.object[obj.propertyKey] = obj.textArea.value;
            obj.feature.updatePropertyOfObservers('', '', '');
            obj.text = obj.textArea.value;
        });
    });
    attachmentsPropTable.insertTBodyRow({elements: [saveButton.button]});
    const resetButton = new IconLabelButton({text: 'Reset to last save'});
    resetButton.button.classList.add('-red');
    resetButton.button.getElementsByClassName('label')[0].classList.add('-white');
    resetButton.button.addEventListener('click', function() {
        textAreaModals.forEach(obj => {
            obj.textArea.value = obj.text;
        });
    });
    attachmentsPropTable.insertTBodyRow({elements: [resetButton.button]});
    return attachmentsPropTable;
}

/**
 * @param {Object} obj - the object that contains nested objects that I want to be able to access and modify
 * @param {string} [namespace=''] - a string that indicates where in the top-level object the nested object exists
 * @returns {Array} an array of actual objects in the top-level object
 */
function _getNestedObjects(obj, namespace='') {
    const objects = [];
    for (const [k, v] of Object.entries(obj)) {
        // - I don't care if nulls and arrays are returned. Maybe I'll care about them eventually
        if (typeof v === 'object' && v !== null) {
            let objNamespace;
            if (namespace === '') {
                objNamespace = k;
            } else {
                objNamespace = `${namespace}|${k}`;
            }
            objects.push({
                namespace: objNamespace,
                object: v
            });
            objects.push(..._getNestedObjects(v, k));
        }
    }
    return objects;
}

/**
 * - David wanted "save" and "cancel" buttons, so not all of these parameters are used anymore. Instead, these parameters are used to understand what
 *   the "save" and "cancel" buttons do
 * @param {string} title
 * @param {string} propertyKey
 * @param {string} text
 * @param {Object} object - the object that contains the key and value that created the text area
 * @param {Feature} feature - the Feature that will have updatePropertyOfObservers() called on it (i.e. the "omd" feature)
 * @returns {PropTable}
 */
function _getTextAreaTable(title, propertyKey, text, object, feature) {
    if (typeof title !== 'string') {
        throw TypeError('The "title" argument must be typeof string.');
    }
    if (typeof propertyKey !== 'string') {
        throw TypeError('The "propertyKey" argument must be typeof string.');
    }
    if (typeof text !== 'string') {
        throw TypeError('The "text" argument must be typeof string.');
    }
    if (typeof object !== 'object') {
        throw TypeError('The "object" argument must be typeof object.');
    }
    const propTable = new PropTable();
    propTable.insertTBodyRow({elements: [title]});
    const textArea = document.createElement('textarea');
    textArea.value = text;
    //textArea.addEventListener('change', function() {
    //    object[propertyKey] = textArea.value;
    //    feature.updatePropertyOfObservers('', '', '');
    //});
    propTable.insertTBodyRow({elements: [textArea]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getAttachmentsButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('"controller" argument must be instanceof FeatureController.');
    }
    const button = new IconLabelButton({text: 'Attachments...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        const propTable = _getAttachmentsTable(controller);
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getClimateTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['Climate change']});
    // - Climate import select
    const climateImportSelect = document.createElement('select');
    climateImportSelect.name = 'climateImportOption';
    let option = document.createElement('option');
    option.text = 'USCRN import';
    option.value = 'USCRNImport';
    climateImportSelect.add(option);
    option = document.createElement('option');
    option.text = 'tmy import';
    option.value = 'tmyImport';
    climateImportSelect.add(option);
    propTable.insertTBodyRow({elements: [climateImportSelect]});
    // - USCRN dropdown
    const uscrnDropdown = new DropdownDiv();
    uscrnDropdown.div.getElementsByClassName('contentdiv')[0].classList.add('-expanded');
    const uscrnTable = new PropTable();
    // - USCRN year select
    const uscrnYearSelect = document.createElement('select');
    uscrnYearSelect.id = 'uscrnYearSelect';
    uscrnYearSelect.name = 'uscrnYear';
    [2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019].forEach(year => {
        const option = document.createElement('option');
        option.text = year;
        option.value = year;
        uscrnYearSelect.add(option);
    });
    uscrnYearSelect.addEventListener('change', function() {
        observable.setProperty('uscrnYear', this.value, 'formProps');
    });
    uscrnTable.insertTBodyRow({elements: ['Year', uscrnYearSelect]});
    // - USCRN station select
    const uscrnStationSelect = document.createElement('select');
    uscrnStationSelect.name = 'uscrnStation';
    ["AK_Bethel_87_WNW", "AK_Cordova_14_ESE", "AK_Deadhorse_3_S", "AK_Denali_27_N", "AK_Fairbanks_11_NE", "AK_Glennallen_64_N", "AK_Gustavus_2_NE",
	"AK_Ivotuk_1_NNE", "AK_Kenai_29_ENE", "AK_King_Salmon_42_SE", "AK_Metlakatla_6_S", "AK_Port_Alsworth_1_SW", "AK_Red_Dog_Mine_3_SSW", "AK_Ruby_44_ESE",
    "AK_Sand_Point_1_ENE", "AK_Selawik_28_E", "AK_Sitka_1_NE", "AK_St._Paul_4_NE", "AK_Tok_70_SE", "AK_Toolik_Lake_5_ENE", "AK_Utqiagvik_formerly_Barrow_4_ENE",
    "AK_Yakutat_3_SSE", "AL_Brewton_3_NNE", "AL_Clanton_2_NE", "AL_Courtland_2_WSW", "AL_Cullman_3_ENE", "AL_Fairhope_3_NE", "AL_Gadsden_19_N", "AL_Gainesville_2_NE",
	"AL_Greensboro_2_WNW", "AL_Highland_Home_2_S", "AL_Muscle_Shoals_2_N", "AL_Northport_2_S", "AL_Russellville_4_SSE", "AL_Scottsboro_2_NE", "AL_Selma_6_SSE",
	"AL_Selma_13_WNW", "AL_Talladega_10_NNE", "AL_Thomasville_2_S", "AL_Troy_2_W", "AL_Valley_Head_1_SSW", "AR_Batesville_8_WNW", "AZ_Elgin_5_S", "AZ_Tucson_11_W",
	"AZ_Williams_35_NNW", "AZ_Yuma_27_ENE", "CA_Bodega_6_WSW", "CA_Fallbrook_5_NE", "CA_Merced_23_WSW", "CA_Redding_12_WNW", "CA_Santa_Barbara_11_W", "CA_Stovepipe_Wells_1_SW",
	"CA_Yosemite_Village_12_W", "CO_Boulder_14_W", "CO_Cortez_8_SE", "CO_Dinosaur_2_E", "CO_La_Junta_17_WSW", "CO_Montrose_11_ENE", "CO_Nunn_7_NNE", "FL_Everglades_City_5_NE",
	"FL_Sebring_23_SSE", "FL_Titusville_7_E", "GA_Brunswick_23_S", "GA_Newton_8_W", "GA_Newton_11_SW", "GA_Watkinsville_5_SSE", "HI_Hilo_5_S", "HI_Mauna_Loa_5_NNE",
	"IA_Des_Moines_17_E", "ID_Arco_17_SW", "ID_Murphy_10_W", "IL_Champaign_9_SW", "IL_Shabbona_5_NNE", "IN_Bedford_5_WNW", "KS_Manhattan_6_SSW", "KS_Oakley_19_SSW",
	"KY_Bowling_Green_21_NNE", "KY_Versailles_3_NNW", "LA_Lafayette_13_SE", "LA_Monroe_26_N", "ME_Limestone_4_NNW", "ME_Old_Town_2_W", "MI_Chatham_1_SE", "MI_Gaylord_9_SSW",
	"MN_Goodridge_12_NNW", "MN_Sandstone_6_W", "MO_Chillicothe_22_ENE", "MO_Joplin_24_N", "MO_Salem_10_W", "MS_Holly_Springs_4_N", "MS_Newton_5_ENE", "MT_Dillon_18_WSW",
	"MT_Lewistown_42_WSW", "MT_St._Mary_1_SSW", "MT_Wolf_Point_29_ENE", "MT_Wolf_Point_34_NE", "NC_Asheville_8_SSW", "NC_Asheville_13_S", "NC_Durham_11_W", "ND_Jamestown_38_WSW",
	"ND_Medora_7_E", "ND_Northgate_5_ESE", "NE_Harrison_20_SSE", "NE_Lincoln_8_ENE", "NE_Lincoln_11_SW", "NE_Whitman_5_ENE", "NH_Durham_2_N", "NH_Durham_2_SSW", "NM_Las_Cruces_20_N",
	"NM_Los_Alamos_13_W", "NM_Socorro_20_N", "NV_Baker_5_W", "NV_Denio_52_WSW", "NV_Mercury_3_SSW", "NY_Ithaca_13_E", "NY_Millbrook_3_W", "OH_Wooster_3_SSE", "OK_Goodwell_2_E",
	"OK_Goodwell_2_SE", "OK_Stillwater_2_W", "OK_Stillwater_5_WNW", "ON_Egbert_1_W", "OR_Coos_Bay_8_SW", "OR_Corvallis_10_SSW", "OR_John_Day_35_WNW", "OR_Riley_10_WSW",
	"PA_Avondale_2_N", "RI_Kingston_1_NW", "RI_Kingston_1_W", "SC_Blackville_3_W", "SC_McClellanville_7_NE", "SD_Aberdeen_35_WNW", "SD_Buffalo_13_ESE", "SD_Pierre_24_S",
	"SD_Sioux_Falls_14_NNE", "TN_Crossville_7_NW", "TX_Austin_33_NW", "TX_Bronte_11_NNE", "TX_Edinburg_17_NNE", "TX_Monahans_6_ENE", "TX_Muleshoe_19_S", "TX_Palestine_6_WNW",
	"TX_Panther_Junction_2_N", "TX_Port_Aransas_32_NNE", "UT_Brigham_City_28_WNW", "UT_Torrey_7_E", "VA_Cape_Charles_5_ENE", "VA_Charlottesville_2_SSE", "WA_Darrington_21_NNE",
    "WA_Quinault_4_NE", "WA_Spokane_17_SSW", "WI_Necedah_5_WNW", "WV_Elkins_21_ENE", "WY_Lander_11_SSE", "WY_Moose_1_NNE", "WY_Sundance_8_NNW"].forEach(station => {
        const option = document.createElement('option');
        option.text = station;
        option.value = station;
        uscrnStationSelect.add(option); 
    });
    uscrnStationSelect.addEventListener('change', function() {
        observable.setProperty('uscrnStation', this.value, 'formProps');
    });
    uscrnTable.insertTBodyRow({elements: ['Station', uscrnStationSelect]});
    uscrnDropdown.insertElement({element: uscrnTable.div});
    propTable.insertTBodyRow({elements: [uscrnDropdown.div]});
    // - tmy dropdown
    const tmyDropdown = new DropdownDiv();
    const tmyTable = new PropTable();
    // - tmy zip code input
    const tmyInput = document.createElement('input');
    tmyInput.id = 'tmyInput';
    tmyInput.name = 'tmyInput';
    tmyInput.addEventListener('change', function() {
        const value = this.value.trim();
        observable.setProperty('zipCode', value, 'formProps');
    });
    const tmyInputLabel = document.createElement('label');
    tmyInputLabel.htmlFor = 'tmyInput';
    tmyInputLabel.innerText = 'ZIP code';
    tmyTable.insertTBodyRow({elements: [tmyInputLabel, tmyInput]});
    tmyDropdown.insertElement({element: tmyTable.div});
    propTable.insertTBodyRow({elements: [tmyDropdown.div]});
    climateImportSelect.addEventListener('change', function() {
        observable.setProperty('climateImportOption', this.value, 'formProps');
        if (this.value === 'USCRNImport') {
            uscrnDropdown.div.getElementsByClassName('contentdiv')[0].classList.add('-expanded');
            tmyDropdown.div.getElementsByClassName('contentdiv')[0].classList.remove('-expanded');
        } else {
            uscrnDropdown.div.getElementsByClassName('contentdiv')[0].classList.remove('-expanded');
            tmyDropdown.div.getElementsByClassName('contentdiv')[0].classList.add('-expanded');
        }
    });
    // - Submit button
    const button = new IconLabelButton({text: 'Submit'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    // - LoadingSpan
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], position: 'prepend'})
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', async function() {
        modalInsert.removeEventListener('click', hideModalInsert); 
        loadingSpan.update({text: 'Adding climate data...', show: true});
        await controller.submitFeature(observable, loadingSpan, button.button);
    });
    propTable.insertTBodyRow({elements: [button.button]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getClimateButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:climate',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${gThisFeederName}`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/climateChange/${gThisOwner}/${gThisFeederName}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                climateImportOption: 'USCRNImport',
                uscrnStation: 'AK_Bethel_87_WNW',
                uscrnYear: '2006',
                zipCode: ''
            }
        },
        type: 'Feature'
    });
    const propTable =_getClimateTable(feature, controller);
    const button = new IconLabelButton({text: 'Climate...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Feature} observable
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {PropTable}
 */
function _getScadaTable(observable, controller) {
    if (!(observable instanceof Feature)) {
        throw TypeError('The "observable" argument must be instanceof Feature.');
    }
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    // - csv file input
    const scadaInput = document.createElement('input');
    scadaInput.type = 'file';
    scadaInput.accept = '.csv';
    scadaInput.required = true;
    scadaInput.id = 'scadaInput'; 
    scadaInput.addEventListener('change', function() {
        const scadaFile = this.files[0];
        observable.setProperty('scadaFile', scadaFile, 'formProps');
    }); 
    const scadaLabel = document.createElement('label');
    scadaLabel.htmlFor = 'scadaInput';
    scadaLabel.innerHTML = 'File containing SCADA load data (.csv)';
    // - Format help anchor
    const anchor = document.createElement('a');
    anchor.href = 'https://github.com/dpinney/omf/wiki/Tools-~-gridEdit#scada-loadshapes';
    anchor.textContent = 'Format Help';
    anchor.target = '_blank';
    const propTable = new PropTable();
    // - Don't close the modal when it is clicked on
    propTable.div.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    propTable.insertTHeadRow({elements: ['SCADA loadshapes'], colspans: [2]});
    propTable.insertTBodyRow({elements: [anchor]});
    propTable.insertTBodyRow({elements: [scadaLabel, scadaInput]});
    propTable.insertTBodyRow({elements: ['Note: model "Simulation Start Data" should lie within the SCADA load\'s dates.'], colspans: [2]});
    const button = new IconLabelButton({text: 'Import'});
    button.button.classList.add('-blue');
    button.button.getElementsByClassName('label')[0].classList.add('-white');
    const loadingSpan = new LoadingSpan();
    loadingSpan.span.classList.add('-yellow', '-hidden');
    propTable.insertTHeadRow({elements: [loadingSpan.span], colspans: [2], position: 'prepend'})
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        if (scadaInput.checkValidity()) {
            modalInsert.removeEventListener('click', hideModalInsert);
            loadingSpan.update({text: 'Importing file...', show: true});
            controller.submitFeature(observable, loadingSpan, button.button);
        } else {
            scadaInput.reportValidity();
        }
    });
    propTable.insertTBodyRow({elements: [button.button], colspans: [2]});
    return propTable;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getScadaButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const feature = new Feature({
        geometry: { 'coordinates': [null, null], 'type': 'Point' },
        properties: {
            treeKey: 'modal:scada',
            urlProps: {
                fileExistsUrl: {
                    method: 'GET',
                    url: `/uniqObjName/Feeder/${gThisOwner}/${gThisModelName}/${gThisFeederName}`
                },
                pollUrl: {
                    method: 'GET',
                    url: `/checkConversion/${gThisModelName}/${gThisOwner}`
                },
                submitUrl: {
                    method: 'POST',
                    url: `/scadaLoadshape/${gThisOwner}/${gThisFeederName}`
                }
            },
            formProps: {
                modelName: gThisModelName,
                scadaFile: ''
            }
        },
        type: 'Feature'
    });
    const propTable = _getScadaTable(feature, controller);
    const button = new IconLabelButton({text: 'SCADA loadshapes...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(propTable.div);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @param {ColorModal} colorModal - a ColorModal instance
 * @returns {HTMLButtonElement}
 */
function getColorButton(controller, colorModal) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    if (!(colorModal instanceof ColorModal)) {
        throw TypeError('The "colorModal" argument must be instanceof ColorModal.');
    }
    const divElement = colorModal.getDOMElement();
    const button = new IconLabelButton({text: 'Color circuit...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(divElement);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {FeatureController} controller - a ControllerInterface instance
 * @returns {HTMLButtonElement}
 */
function getGeojsonButton(controller) {
    if (!(controller instanceof FeatureController)) {
        throw TypeError('The "controller" argument must be instanceof FeatureController.');
    }
    const geojsonModal = new GeojsonModal([controller.observableGraph.getObservable('omd')], controller);
    const divElement = geojsonModal.getDOMElement();
    const button = new IconLabelButton({text: 'Add GeoJSON data...'});
    button.button.classList.add('-white');
    const modalInsert = document.getElementById('modalInsert');
    button.button.addEventListener('click', function() {
        modalInsert.replaceChildren(divElement);
        modalInsert.classList.add('visible');
    });
    return button.button;
}

/**
 * @param {Nav} nav - a Nav instance
 * @param {TopTab} topTab - a TopTab instance
 * @returns {HTMLButtonElement}
 */
function getSearchButton(nav, topTab) {
    if (!(nav instanceof Nav)) {
        throw TypeError('The "nav" argument must be instanceof Nav.');
    }
    if (!(topTab instanceof TopTab)) {
        throw TypeError('The "topTab" argument must be instanceof TopTab.');
    }
    const button = new IconLabelButton({text: 'Search objects...'});
    button.button.classList.add('-white');
    button.button.addEventListener('click', function() {
        if (nav.sideNavNavElement.classList.contains('open')) {
            if (topTab.getTab('Search Objects').tab.classList.contains('selected')) {
                nav.sideNavNavElement.classList.remove('open');
                nav.sideNavDivElement.classList.remove('open');
                nav.sideNavArticleElement.classList.remove('compressed');
            }
            if (topTab.getTab('Add New Objects').tab.classList.contains('selected')) {
                topTab.selectTab(topTab.getTab('Search Objects').tab);
            }
        } else {
            if (topTab.getTab('Add New Objects').tab.classList.contains('selected')) {
                topTab.selectTab(topTab.getTab('Search Objects').tab);
            }
            nav.sideNavNavElement.classList.add('open');
            nav.sideNavDivElement.classList.add('open');
            nav.sideNavArticleElement.classList.add('compressed');
        }
        document.getElementById('editMenu').getElementsByTagName('button')[0].click();
    });
    return button.button;
}

/**
 * @param {Nav} nav - a Nav instance
 * @param {TopTab} topTab - a TopTab instance
 * @returns {HTMLButtonElement}
 */
function getAddComponentsButton(nav, topTab) {
    if (!(nav instanceof Nav)) {
        throw TypeError('"nav" argument must be instanceof Nav.');
    }
    if (!(topTab instanceof TopTab)) {
        throw TypeError('"topTab" argument must be instanceof TopTab.');
    }
    const button = new IconLabelButton({text: 'Add new objects'});
    button.button.classList.add('-white');
    button.button.addEventListener('click', function() {
        if (nav.sideNavNavElement.classList.contains('open')) {
            if (topTab.getTab('Add New Objects').tab.classList.contains('selected')) {
                nav.sideNavNavElement.classList.remove('open');
                nav.sideNavDivElement.classList.remove('open');
                nav.sideNavArticleElement.classList.remove('compressed');
            }
            if (topTab.getTab('Search Objects').tab.classList.contains('selected')) {
                topTab.selectTab(topTab.getTab('Add New Objects').tab);
            }
        } else {
            if (topTab.getTab('Search Objects').tab.classList.contains('selected')) {
                topTab.selectTab(topTab.getTab('Add New Objects').tab);
            }
            nav.sideNavNavElement.classList.add('open');
            nav.sideNavDivElement.classList.add('open');
            nav.sideNavArticleElement.classList.add('compressed');
        }
        document.getElementById('editMenu').getElementsByTagName('button')[0].click();
    });
    return button.button;
}

/*********************************/
/* Private convenience functions */
/*********************************/

/**
 * - Firefox doesn't display the reportValidity() message correctly
 * - I don't know why I can't get actual regular expression literals to work. Only the regex string works for me
 * @param {Feature} observable
 * @param {Function} func - a function that takes the new name as an argument
 * @returns {HTMLInputElement}
 */
function _getNameInput(observable, func) {
    const input = document.createElement('input');
    input.pattern = '(?:\\w+-?\\s?)+';
    input.placeholder = 'New name';
    input.required = true;
    input.title = 'The new name must have one or more alphanumeric characters. Single spaces, hyphens, and underscores are allowed.';
    input.addEventListener('change', function() {
        this.setCustomValidity('');
        if (this.validity.valueMissing || this.validity.patternMismatch) {
            input.setCustomValidity('The new name must have one or more alphanumeric characters. Single spaces, hyphens, and underscores are allowed.');
            input.reportValidity();
        } else if (this.validity.valid) {
            func(this.value.trim());
        }
    });
    return input
}