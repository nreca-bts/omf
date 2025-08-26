export { LeafletLayer };
import { Feature } from './feature.js';
import { FeatureController } from "./featureController.js";
import { FeatureEditModal } from './featureEditModal.js';
import { ClusterControlClass } from './clusterControl.js';

/**
 * - Each LeafletLayer instance is a view in the MVC pattern. Each observes an ObservableInterface instance, which is part of the model in the MVC
 *   pattern. An ObservableInterface instance does NOT observe a LeafletLayer instance. Instead, a LeafletLayer instance uses the controller to pass
 *   its own changes to the underlying ObservableInterface instance
 */
class LeafletLayer {    // implements ObserverInterface
    #controller;        // ControllerInterface instance
    #layer;             // - Leaflet layer
    #observable;        // - ObservableInterface instance
    #modal;
    static trackCursor = null;  // - HACK: the currently active trackCusor function. This is needed to get rid of sticky markers when the map gets a mouseup event
    static map = null;
    static control = null;
    static nodeLayers = L.featureGroup();
    static lineLayers = L.featureGroup();
    static parentChildLineLayers = L.featureGroup();
    static nodeClusterLayers = L.markerClusterGroup();
    static clusterControl = null;

    /**
     * @param {Feature} observable - an ObservableInterface instance
     * @param {FeatureController} controller - a ControllerInterface instance
     * @returns {undefined}
     */
    constructor(observable, controller) {
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instance of Feature.');
        }
        if (!(controller instanceof FeatureController)) {
            throw Error('The "controller" argument must be an instance of FeatureController.');
        }
        this.#controller = controller;
        this.#observable = observable;
        // - Here, the first observer is added to every visible feature
        this.#observable.registerObserver(this);
        const feature = {'type': 'Feature', 'geometry': {}};
        if (this.#observable.isNode()) {
            feature.geometry.type = 'Point';
        } else if (this.#observable.isLine()) {
            feature.geometry.type = 'LineString';
        } else if (this.#observable.isPolygon()) {
            feature.geometry.type = 'Polygon';
        } else if (this.#observable.isMultiPoint()) {
            feature.geometry.type = 'MultiPoint';
        } else if (this.#observable.isMultiLineString()) {
            feature.geometry.type = 'MultiLineString';
        } else if (this.#observable.isMultiPolygon()) {
            feature.geometry.type = 'MultiPolygon';
        } else {
            throw Error('The observable does not reference a valid GeoJSON feature (is it a configuration object or GeometryCollection?)');
        }
        feature.geometry.coordinates = structuredClone(this.#observable.getCoordinates());
        feature.properties = structuredClone(this.#observable.getProperties('meta'));
        // - L.geoJSON() returns an instance of https://leafletjs.com/reference.html#geojson
        //  - A GeoJSON object extends FeatureGroup which extends LayerGroup which extends Layer
        //  - Therefore, a GeoJSON object can contain one or more layers
        //  - Access the underlying layer(s) with <GeoJSON>._layers, which is a map (i.e. object) that maps layer ids to actual layer objects
        this.#layer = L.geoJSON(feature, {
            pointToLayer: this.#pointToLayer.bind(this), 
            style: this.#style.bind(this),
        });
        this.#layer.addEventListener('popupclose', () => {
            this.#observable.removeObserver(this.#modal);
        });
        if (this.#observable.isLine() || this.#observable.isPolygon() || this.#observable.isMultiPolygon()) {
            this.bindPopup();
        }
    }

    // *******************************
    // ** ObserverInterface methods ** 
    // *******************************

    /**
     * - Remove this ObserverInterface instance (i.e. "this") from the ObservableInterface instance (i.e. "observable") that has been deleted, and
     *   perform other actions as needed
     *  - E.g. delete this layer if its underlying feature was deleted
     * @param {Object} observable - an instance of ObservableInterface that this Observer is observing
     * @returns {undefined}
     */
    handleDeletedObservable(observable) {
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instance of Feature.');
        }
        // - The function signature above is part of the ObserverInterface API. The implementation below is not
        observable.removeObserver(this);
        const layer = Object.values(this.#layer._layers)[0]; 
        // - Why does this also delete the FeatureEditModal in the pop-up? I don't know but I have to deal with it
        layer.remove();
        // - Need to explicitly remove the underlying layer from its LayerGroup
        if (observable.isNode()) {
            LeafletLayer.nodeLayers.removeLayer(this.#layer);
            LeafletLayer.nodeClusterLayers.removeLayer(this.#layer);
        } else if (observable.isLine()) {
            if (observable.isParentChildLine()) {
                LeafletLayer.parentChildLineLayers.removeLayer(this.#layer);
            } else {
                LeafletLayer.lineLayers.removeLayer(this.#layer);
            }
        } else if (observable.isPolygon()) {
            // - Do nothing for now
        } else if (observable.isMultiPoint()) {
            // - Do nothing for now
        } else if (observable.isMultiLineString()) {
            // - Do nothing for now
        } else if (observable.isMultiPolygon()) {
            // - Do nothing for now
        } else {
            throw Error('The observable does not reference a valid GeoJSON feature (is it a configuration object or GeometryCollection?)');
        }
    }

    /**
     * - Update this ObserverInterface instance (i.e. "this") based on the coordinates of the ObservableInterface instance (i.e. "observable") that
     *   have just changed and perform other actions as needed
     *  - E.g. update this layer's coordinates if the coordinates of the underlying feature changed
     * @param {Object} observable - an instance of ObservableInterface that this Observer is observing
     * @param {Array} oldCoordinates - the old coordinates of the observable prior to the change in coordinates
     * @param {Array} visited - an array of ObserverInterface instances. It's required to prevent infinite recursion caused by Observers updating each
     * other
     * @returns {undefined}
     */
    handleUpdatedCoordinates(observable, oldCoordinates) {
        // - The function signature above is part of the ObserverInterface API. The implementation below is not
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instance of Feature.');
        }
        if (!(oldCoordinates instanceof Array)) {
            throw TypeError('The "oldCoordinates" argument must be an array.')
        }
        const coordinates = observable.getCoordinates();
        if (observable.isNode()) {
            // - Object.values(this.<GeoJSON>.<mapping object>)[0] === <Layer>
            Object.values(this.#layer._layers)[0].setLatLng([coordinates[1], coordinates[0]]);
        } else {
            Object.values(this.#layer._layers)[0].setLatLngs([[coordinates[0][1], coordinates[0][0]],[coordinates[1][1], coordinates[1][0]]]);
        }
    }

    /**
     * - Update this ObserverInstance (i.e. "this") based on the property of the ObservableInterface instance (i.e. "observable") that has just
     *   changed and perform other actions as needed
     *  - E.g. update this line's "to" and/or "from" property to match the "name" property of the node that was just changed
     * @param {Object} observable - the observable that this observer is observing
     * @param {string} propertyKey - the property key of the property that has been created/changed/deleted in the observable
     * @param {(string|Object)} oldPropertyValue - the previous value of the property that has been created/changed/deleted in the observable
     * @param {string} namespace - the namespace of the property that has been created/changed/deleted in the observable
     * @returns {undefined}
     */
    handleUpdatedProperty(observable, propertyKey, oldPropertyValue, namespace='treeProps') {
        // - The function signature above is part of the ObserverInterface API. The implementation below is not
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instance of Feature.');
        }
        if (typeof propertyKey !== 'string') {
            throw TypeError('"propertyKey" argument must be a string.');
        }
        if (typeof namespace !== 'string') {
            throw TypeError('"namespace" argument must be a string.');
        }
        // - Currently, we don't need to do anything like change the color of a node in response to a property change, but we could
    }

    // ********************
    // ** Public methods **
    // ********************

    bindPopup() {
        const layer = Object.values(this.#layer._layers)[0];
        layer.bindPopup(
            () => {
                this.#modal = new FeatureEditModal(this.#observable, this.#controller);
                return this.#modal.getDOMElement();
            },
            // - I CANNOT set this option because then the popup won't follow a node around when it is dragged!
            //{ closeButton: false }
        );
    }

    unbindPopup() {
        Object.values(this.#layer._layers)[0].unbindPopup();
    }

    /**
     * - Creating a LeafletLayer with the constructor does not automatically add the underlying layer to a layer group by design. This function must
     *   be called explicitly, or LayerGroups must be managed outside of this function
     * @param {LeafletLayer} - layer
     * @returns {undefined}
     */
    static createAndGroupLayer(observable, controller) {
        if (!(observable instanceof Feature)) {
            throw TypeError('The "observable" argument must be instanceof Feature.');
        }
        if (!(controller instanceof FeatureController)) {
            throw TypeError('The "controller" argument must be instanceof FeatureController.');
        }
        const ll = new LeafletLayer(observable, controller);
        if (observable.isNode()) {
            // - If clustering is active and a component is added, then the layer of the component should go into the nodeClusterLayers group (very
            //   rare case but it's good to cover it)
            if (LeafletLayer.clusterControl._on) {
                LeafletLayer.nodeClusterLayers.addLayer(ll.getLayer());
            } else {
                LeafletLayer.nodeLayers.addLayer(ll.getLayer());
            }
        } else if (observable.isLine()) {
            if (observable.isParentChildLine()) {
                LeafletLayer.parentChildLineLayers.addLayer(ll.getLayer());
            } else {
                LeafletLayer.lineLayers.addLayer(ll.getLayer());
            }
        } else if (observable.isPolygon()) {
            // - Do nothing for now
        } else if (observable.isMultiPoint()) {
            // - Do nothing for now
        } else if (observable.isMultiLineString()) {
            // - Do nothing for now
        } else if (observable.isMultiPolygon()) {
            // - Do nothing for now
        } else {
            throw Error('The observable does not reference a valid GeoJSON feature (is it a configuration object or GeometryCollection?)');
        }
    }

    /**
     * @returns {GeoJSON}
     */
    getLayer() {
        return this.#layer;
    }

    /**
     * - Iterate through all observables and put every visible observable back into its proper layer group
     * - This has to be static because it shouldn't need to be called off of any particular instance
     * @returns {undefined}
     */
    static resetLayerGroups(controller) {
        if (!(controller instanceof FeatureController)) {
            throw TypeError('The "controller" argument must be instanceof FeatureController.');
        }
        for (const observable of controller.observableGraph.getObservables()) {
            if (observable.isNode() && !observable.isConfigurationObject()) {
                const ll = observable.getObservers().filter(observer => observer instanceof LeafletLayer)[0];
                if (LeafletLayer.clusterControl._on) {
                    LeafletLayer.nodeClusterLayers.addLayer(ll.getLayer());
                } else {
                    LeafletLayer.nodeLayers.addLayer(ll.getLayer());
                }
            } else if (observable.isLine()) {
                const ll = observable.getObservers().filter(observer => observer instanceof LeafletLayer)[0];
                if (observable.isParentChildLine()) {
                    LeafletLayer.parentChildLineLayers.addLayer(ll.getLayer());
                } else {
                    LeafletLayer.lineLayers.addLayer(ll.getLayer());
                }
            }
        }
        // - Force redraw
        for (const layer of [LeafletLayer.parentChildLineLayers, LeafletLayer.lineLayers, LeafletLayer.nodeLayers, LeafletLayer.nodeClusterLayers]) {
            LeafletLayer.map.removeLayer(layer);
            LeafletLayer.map.addLayer(layer);
        }
    }

    // *********************
    // ** Private methods ** 
    // *********************

    #pointToLayer(feature, latlng) {
        const marker = L.circleMarker(latlng);
        // - Make circle marker draggable
        const trackCursor = (e) => {
            this.#controller.setCoordinates([this.#observable], [e.latlng.lng, e.latlng.lat]);
        };
        const mousedownPoint = {
            lat: null,
            lng: null
        };
        marker.on('mousedown', (e) => {
            // - Don't let the map get the mousedown event. This matters for multiselectControl.js
            L.DomEvent.stopPropagation(e);
            this.bindPopup();
            mousedownPoint.lat = e.latlng.lat;
            mousedownPoint.lng = e.latlng.lng;
            LeafletLayer.map.dragging.disable();
            LeafletLayer.map.on('mousemove', trackCursor);
            LeafletLayer.trackCursor = trackCursor;
        });
        marker.on('mouseup', (e) => {
            // - Don't let the map get the mouseup event. This matters for multiselectControl.js
            L.DomEvent.stopPropagation(e);
            LeafletLayer.map.dragging.enable();
            LeafletLayer.map.off('mousemove', trackCursor)
            LeafletLayer.trackCursor = null;
            if (e.latlng.lat !== mousedownPoint.lat || e.latlng.lng !== mousedownPoint.lng) {
                this.unbindPopup();
            }
            mousedownPoint.lat = null;
            mousedownPoint.lng = null;
        });
        return marker;
    }

    #style() {
        // - Extension styling
        if (this.#observable.hasProperty('SOVI_RATNG', 'meta') && this.#observable.getProperty('SOVI_RATNG', 'meta') === 'Very High') {
            return {
                color: 'yellow'
            }
        } else if (this.#observable.hasProperty('SOVI_RATNG', 'meta') && this.#observable.getProperty('SOVI_RATNG', 'meta') === 'Relatively High') {
            return {
                color: '#83d54b'
            }
        } else if (this.#observable.hasProperty('SOVI_RATNG', 'meta') && this.#observable.getProperty('SOVI_RATNG', 'meta') === 'Relatively Moderate') {
            return {
                color: 'mediumspringgreen'
            }
        } else if (this.#observable.hasProperty('SOVI_RATNG', 'meta') && this.#observable.getProperty('SOVI_RATNG', 'meta') === 'Relatively Low') {
            return {
                color: 'cyan'
            }
        } else if (this.#observable.hasProperty('SOVI_RATNG', 'meta') && this.#observable.getProperty('SOVI_RATNG', 'meta') === 'Very Low') {
            return {
                color: 'blue'
            }
        }
        // - Default OMF editor styling
        if (this.#observable.isNode()) {
            let fillColor = 'gray';
            if (this.#observable.hasProperty('pointColor')) {
                fillColor = this.#observable.getProperty('pointColor');
            } else if (this.#observable.hasProperty('object')) {
                const object = this.#observable.getProperty('object');
                if (object === 'capacitor') {
                    fillColor = 'purple';
                }
                if (object === 'generator') {
                    fillColor = 'red';
                }
                if (object == 'load') {
                    fillColor = 'blue';
                }
            }
            return {
                color: 'black',
                fillColor: fillColor,
                fillOpacity: .9,
                radius: 6.5,
                weight: 1.5
            }
        }
        if (this.#observable.isParentChildLine()) {
            return {
                color: 'black',
                // - Dashed lines are only useful if the child is reasonably far from the parent, so I need other differences in style
                dashArray: '.5 10',
                lineCap: 'square',
                weight: '3'
            }
        }
        if (this.#observable.isLine()) {
            let color = 'black';
            if (this.#observable.hasProperty('edgeColor')) {
                color = this.#observable.getProperty('edgeColor')
            } else if (this.#observable.hasProperty('object')) {
                const object = this.#observable.getProperty('object');
                if (object === 'transformer') {
                    color = 'orange';
                } else if (object === 'regulator') {
                    color = 'red';
                } else if (object === 'underground_line') {
                    color = 'gray';
                }

            }
            return {
                color: color
            }
        }
        return {
            color: 'blue'
        }
    }
}
